import json
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import asyncpg
import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer
from dotenv import load_dotenv
from loguru import logger
from PIL import Image
from redis.asyncio import Redis

from app.application import create_app
from app.config import (
    ApiSettings,
    AuthSettings,
    DatabaseSettings,
    LoggingSettings,
    RedisSettings,
    Settings,
    StorageSettings,
)
from app.db.migrate import apply_migrations
from app.dependencies import DATABASE_KEY, REDIS_KEY, STORAGE_KEY
from app.task_queue.redis import RedisTaskQueue
from app.worker.consumer import TaskWorker
from app.worker.processor import ImageProcessor


async def test_real_upload_worker_get_pipeline(tmp_path: Path) -> None:
    """Проверяет полную цепочку с PostgreSQL и Redis."""
    load_dotenv()
    postgres_dsn = os.getenv("TEST_POSTGRES_DSN", "").strip()
    redis_dsn = os.getenv("TEST_REDIS_DSN", "").strip()
    if not postgres_dsn or not redis_dsn:
        pytest.skip(
            "Для E2E нужны TEST_POSTGRES_DSN и TEST_REDIS_DSN"
        )

    schema = f"test_image_service_{uuid4().hex}"
    queue_name = f"test_image_tasks_{uuid4().hex}"
    separator = "&" if "?" in postgres_dsn else "?"
    scoped_dsn = (
        f"{postgres_dsn}{separator}search_path={quote(schema)}"
    )
    admin_connection = None
    redis_admin = None
    client = None
    schema_created = False
    log_path = tmp_path / "e2e.jsonl"

    try:
        admin_connection = await asyncpg.connect(postgres_dsn)
        await admin_connection.execute(f'CREATE SCHEMA "{schema}"')
        schema_created = True

        redis_admin = Redis.from_url(
            redis_dsn,
            decode_responses=True,
        )
        await redis_admin.ping()
        await redis_admin.delete(
            queue_name,
            f"{queue_name}:processing",
        )

        settings = Settings(
            api=ApiSettings(
                max_upload_size_bytes=1024 * 1024,
                max_image_dimension=1000,
                max_image_pixels=1_000_000,
            ),
            database=DatabaseSettings(
                dsn=scoped_dsn,
                min_pool_size=1,
                max_pool_size=2,
            ),
            redis=RedisSettings(
                dsn=redis_dsn,
                queue_name=queue_name,
            ),
            auth=AuthSettings(bearer_token="e2e-token"),
            storage=StorageSettings(image_directory=tmp_path),
            logging=LoggingSettings(
                enabled=True,
                stdout=False,
                file=True,
                file_path=log_path,
            ),
        )
        await apply_migrations(settings.database)

        app = create_app(settings)
        client = TestClient(TestServer(app))
        await client.start_server()
        headers = {"Authorization": "Bearer e2e-token"}

        source = BytesIO()
        Image.new("RGBA", (8, 6), (255, 0, 0, 128)).save(
            source,
            format="PNG",
        )
        form = FormData()
        form.add_field(
            "file",
            source.getvalue(),
            filename="source.png",
            content_type="image/png",
        )
        form.add_field("quality", "80")
        form.add_field("x", "4")
        form.add_field("y", "3")

        upload_response = await client.post(
            "/api/images",
            data=form,
            headers=headers,
        )
        assert upload_response.status == 202
        task_id = UUID((await upload_response.json())["task_id"])

        queue = RedisTaskQueue(
            client=app[REDIS_KEY],
            queue_name=queue_name,
        )
        message = await queue.reserve(timeout=1)
        assert message is not None
        assert message.task_id == task_id

        worker = TaskWorker(
            database=app[DATABASE_KEY],
            queue=queue,
            storage=app[STORAGE_KEY],
            processor=ImageProcessor(
                max_image_dimension=settings.api.max_image_dimension,
                max_image_pixels=settings.api.max_image_pixels,
            ),
        )
        await worker.process_task(task_id)
        await queue.acknowledge(message)

        task_response = await client.get(
            f"/api/tasks/{task_id}",
            headers=headers,
        )
        assert task_response.status == 200
        task_payload = await task_response.json()
        assert task_payload["status"] == "completed"
        image_id = UUID(task_payload["image_id"])

        image_response = await client.get(
            f"/api/images/{image_id}",
            headers=headers,
        )
        assert image_response.status == 200
        assert image_response.content_type == "image/jpeg"
        image_content = await image_response.read()

        with Image.open(BytesIO(image_content)) as result:
            assert result.format == "JPEG"
            assert result.size == (4, 3)

        metadata_response = await client.get(
            f"/api/images/{image_id}/metadata",
            headers=headers,
        )
        metadata = await metadata_response.json()
        assert metadata["quality"] == 80
        assert metadata["width"] == 4
        assert metadata["height"] == 3
        assert list(tmp_path.glob("*.upload")) == []

        await client.close()
        client = None
        records = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
        ]
        assert any(
            record["endpoint"] == "/api/images"
            and record["status_code"] == 202
            for record in records
        )
    finally:
        try:
            if client is not None:
                await client.close()
        finally:
            try:
                if redis_admin is not None:
                    try:
                        await redis_admin.delete(
                            queue_name,
                            f"{queue_name}:processing",
                        )
                    finally:
                        await redis_admin.aclose()
            finally:
                try:
                    if admin_connection is not None:
                        try:
                            if schema_created:
                                await admin_connection.execute(
                                    f'DROP SCHEMA "{schema}" CASCADE'
                                )
                        finally:
                            await admin_connection.close()
                finally:
                    await logger.complete()
                    logger.remove()

