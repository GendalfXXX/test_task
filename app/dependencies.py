from typing import TYPE_CHECKING

from aiohttp import web
from redis.asyncio import Redis

from app.config import Settings
from app.db.database import Database
from app.storage.filesystem import FileSystemStorage

if TYPE_CHECKING:
    from app.services.image_service import ImageService
    from app.services.log_service import LogService
    from app.services.task_service import TaskService


SETTINGS_KEY = web.AppKey("settings", Settings)
DATABASE_KEY = web.AppKey("database", Database)
REDIS_KEY = web.AppKey("redis", Redis)
STORAGE_KEY = web.AppKey("storage", FileSystemStorage)


def get_image_service(request: web.Request) -> "ImageService":
    """Собирает сервис изображений из контекста приложения."""
    from app.task_queue.redis import RedisTaskQueue
    from app.services.image_service import ImageService

    settings = request.app[SETTINGS_KEY]
    queue = RedisTaskQueue(
        client=request.app[REDIS_KEY],
        queue_name=settings.redis.queue_name,
    )
    return ImageService(
        database=request.app[DATABASE_KEY],
        queue=queue,
        storage=request.app[STORAGE_KEY],
    )


def get_task_service(request: web.Request) -> "TaskService":
    """Собирает сервис задач из контекста приложения."""
    from app.services.task_service import TaskService

    return TaskService(database=request.app[DATABASE_KEY])


def get_log_service(request: web.Request) -> "LogService":
    """Собирает сервис чтения логов из настроек приложения."""
    from app.services.log_service import LogService

    return LogService(settings=request.app[SETTINGS_KEY].logging)
