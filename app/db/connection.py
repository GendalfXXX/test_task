from typing import AsyncIterator

from aiohttp import web

from app.db.database import Database
from app.dependencies import DATABASE_KEY, SETTINGS_KEY


async def database_context(
    app: web.Application,
) -> AsyncIterator[None]:
    """Подключает и закрывает PostgreSQL вместе с API."""
    database = Database(app[SETTINGS_KEY].database)
    await database.connect()
    app[DATABASE_KEY] = database

    try:
        yield
    finally:
        await database.close()
