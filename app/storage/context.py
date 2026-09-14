from typing import AsyncIterator

from aiohttp import web

from app.dependencies import SETTINGS_KEY, STORAGE_KEY
from app.storage.filesystem import FileSystemStorage


async def storage_context(
    app: web.Application,
) -> AsyncIterator[None]:
    """Подготавливает файловое хранилище для API."""
    storage = FileSystemStorage(
        app[SETTINGS_KEY].storage.image_directory
    )
    await storage.prepare()
    app[STORAGE_KEY] = storage

    yield
