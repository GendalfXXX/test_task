"""Точка запуска процесса обработки изображений."""

import asyncio

from loguru import logger
from redis.asyncio import Redis

from app.config import Settings, load_settings
from app.db.database import Database
from app.logging_config import configure_logging
from app.task_queue.redis import RedisTaskQueue
from app.storage.filesystem import FileSystemStorage
from app.worker.consumer import TaskWorker
from app.worker.processor import ImageProcessor


async def run_worker(settings: Settings) -> None:
    """Создаёт ресурсы и запускает цикл обработки задач."""
    database = Database(settings.database)
    redis_client = Redis.from_url(
        settings.redis.dsn.get_secret_value(),
        decode_responses=True,
    )
    storage = FileSystemStorage(settings.storage.image_directory)

    try:
        await storage.prepare()
        await database.connect()
        await redis_client.ping()

        queue = RedisTaskQueue(
            client=redis_client,
            queue_name=settings.redis.queue_name,
        )
        worker = TaskWorker(
            database=database,
            queue=queue,
            storage=storage,
            processor=ImageProcessor(
                max_image_dimension=settings.api.max_image_dimension,
                max_image_pixels=settings.api.max_image_pixels,
            ),
        )
        await worker.run_forever()
    finally:
        # Каждый ресурс закрывается, даже если предыдущий завершился с ошибкой.
        try:
            await redis_client.aclose()
        finally:
            try:
                await database.close()
            finally:
                await logger.complete()


def main() -> None:
    """Загружает настройки и запускает процесс воркера."""
    settings = load_settings()
    configure_logging(settings.logging)

    try:
        asyncio.run(run_worker(settings))
    except KeyboardInterrupt:
        logger.info("worker_stopped")


if __name__ == "__main__":
    main()
