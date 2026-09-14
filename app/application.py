from aiohttp import web

from app.api import setup_routes
from app.config import Settings
from app.db.connection import database_context
from app.dependencies import SETTINGS_KEY
from app.logging_config import configure_logging, logging_context
from app.task_queue.redis import redis_context
from app.storage.context import storage_context
from app.middlewares import (
    auth_middleware,
    error_middleware,
    logging_middleware,
    request_id_middleware,
)


def create_app(settings: Settings) -> web.Application:
    """Создаёт и настраивает aiohttp-приложение."""
    configure_logging(settings.logging)

    app = web.Application(
        client_max_size=settings.api.max_upload_size_bytes,
        middlewares=[
            request_id_middleware,
            logging_middleware,
            auth_middleware,
            error_middleware,
        ]
    )

    app[SETTINGS_KEY] = settings
    app.cleanup_ctx.extend(
        [
            logging_context,
            storage_context,
            database_context,
            redis_context,
        ]
    )

    setup_routes(app)
    return app
