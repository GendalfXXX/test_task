from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from loguru import logger
from redis.exceptions import RedisError

from app.api import setup_routes
from app.config import (
    ApiSettings,
    AuthSettings,
    DatabaseSettings,
    LoggingSettings,
    RedisSettings,
    Settings,
    StorageSettings,
)
from app.dependencies import (
    DATABASE_KEY,
    REDIS_KEY,
    SETTINGS_KEY,
    STORAGE_KEY,
)
from app.middlewares import (
    auth_middleware,
    error_middleware,
    logging_middleware,
    request_id_middleware,
)
from app.storage.filesystem import FileSystemStorage


class FakeTaskRepository:
    """Хранит задачи API в памяти теста."""

    def __init__(self) -> None:
        """Создаёт пустое хранилище задач."""
        self.rows: Dict[UUID, Dict[str, Any]] = {}
        self.fail_delete = False

    async def create_upload(
        self,
        task_id: UUID,
        source_path: str,
        original_filename: str,
        quality: Optional[int],
        target_width: Optional[int],
        target_height: Optional[int],
    ) -> Dict[str, Any]:
        """Создаёт тестовую upload-задачу."""
        row = self._row(
            task_id=task_id,
            task_type="upload",
            source_path=source_path,
            original_filename=original_filename,
            source_image_id=None,
            quality=quality,
            target_width=target_width,
            target_height=target_height,
        )
        self.rows[task_id] = row
        return row

    async def create_resize(
        self,
        task_id: UUID,
        source_image_id: UUID,
        target_width: int,
        target_height: int,
    ) -> Dict[str, Any]:
        """Создаёт тестовую resize-задачу."""
        row = self._row(
            task_id=task_id,
            task_type="resize",
            source_path=None,
            original_filename=None,
            source_image_id=source_image_id,
            quality=None,
            target_width=target_width,
            target_height=target_height,
        )
        self.rows[task_id] = row
        return row

    async def get_by_id(
        self,
        task_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Возвращает тестовую задачу."""
        return self.rows.get(task_id)

    async def delete_pending(self, task_id: UUID) -> None:
        """Удаляет ожидающую тестовую задачу."""
        if self.fail_delete:
            raise RuntimeError("Test database cleanup failed")
        self.rows.pop(task_id, None)

    @staticmethod
    def _row(
        task_id: UUID,
        task_type: str,
        source_path: Optional[str],
        original_filename: Optional[str],
        source_image_id: Optional[UUID],
        quality: Optional[int],
        target_width: Optional[int],
        target_height: Optional[int],
    ) -> Dict[str, Any]:
        """Формирует общие поля тестовой задачи."""
        now = datetime.now(timezone.utc)
        return {
            "id": task_id,
            "task_type": task_type,
            "status": "pending",
            "source_path": source_path,
            "original_filename": original_filename,
            "source_image_id": source_image_id,
            "result_image_id": None,
            "quality": quality,
            "target_width": target_width,
            "target_height": target_height,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }


class FakeImageRepository:
    """Хранит изображения API в памяти теста."""

    def __init__(self) -> None:
        """Создаёт пустое хранилище изображений."""
        self.rows: Dict[UUID, Dict[str, Any]] = {}

    async def get_by_id(
        self,
        image_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Возвращает изображение с контентом."""
        return self.rows.get(image_id)

    async def get_metadata_by_id(
        self,
        image_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Возвращает параметры изображения."""
        row = self.rows.get(image_id)
        if row is None:
            return None
        return {
            key: value
            for key, value in row.items()
            if key != "content"
        }

    async def list_metadata(
        self,
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        """Возвращает страницу параметров изображений."""
        rows = sorted(
            self.rows.values(),
            key=lambda row: (row["created_at"], str(row["id"])),
            reverse=True,
        )
        return [
            {
                key: value
                for key, value in row.items()
                if key != "content"
            }
            for row in rows[offset:offset + limit]
        ]


class FakeDatabase:
    """Объединяет тестовые репозитории."""

    def __init__(self) -> None:
        """Создаёт репозитории задач и изображений."""
        self.tasks = FakeTaskRepository()
        self.images = FakeImageRepository()


class FakeRedis:
    """Имитирует добавление задач в Redis."""

    def __init__(self) -> None:
        """Создаёт пустую очередь."""
        self.items = []
        self.fail = False

    async def lpush(self, queue_name: str, task_id: str) -> int:
        """Добавляет тестовое сообщение в начало списка."""
        if self.fail:
            raise RedisError("Redis is unavailable")

        self.items.insert(0, (queue_name, task_id))
        return len(self.items)


@dataclass
class ApiContext:
    """Хранит зависимости интеграционного теста."""

    client: TestClient
    database: FakeDatabase
    redis: FakeRedis
    storage_path: Path
    log_path: Path
    token: str

    @property
    def auth_headers(self) -> Dict[str, str]:
        """Возвращает заголовок авторизации."""
        return {"Authorization": f"Bearer {self.token}"}


@pytest_asyncio.fixture
async def api_context(tmp_path: Path) -> ApiContext:
    """Запускает aiohttp-приложение с тестовыми зависимостями."""
    token = "test-token"
    log_path = tmp_path / "application.jsonl"
    settings = Settings(
        api=ApiSettings(
            max_upload_size_bytes=1024 * 1024,
            max_image_dimension=10_000,
            image_list_limit=100,
        ),
        database=DatabaseSettings(
            dsn="postgresql://unused",
        ),
        redis=RedisSettings(
            dsn="redis://unused",
            queue_name="image_tasks",
        ),
        auth=AuthSettings(bearer_token=token),
        storage=StorageSettings(image_directory=tmp_path),
        logging=LoggingSettings(
            enabled=True,
            stdout=False,
            file=True,
            file_path=log_path,
            read_limit=100,
            max_read_limit=1000,
        ),
    )
    logger.remove()

    database = FakeDatabase()
    redis = FakeRedis()
    storage = FileSystemStorage(tmp_path)
    await storage.prepare()

    app = web.Application(
        client_max_size=settings.api.max_upload_size_bytes,
        middlewares=[
            request_id_middleware,
            logging_middleware,
            auth_middleware,
            error_middleware,
        ],
    )
    app[SETTINGS_KEY] = settings
    app[DATABASE_KEY] = database
    app[REDIS_KEY] = redis
    app[STORAGE_KEY] = storage
    setup_routes(app)

    client = TestClient(TestServer(app))
    await client.start_server()
    context = ApiContext(
        client=client,
        database=database,
        redis=redis,
        storage_path=tmp_path,
        log_path=log_path,
        token=token,
    )

    try:
        yield context
    finally:
        await client.close()
        logger.remove()
