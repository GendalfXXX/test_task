from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import asyncpg

from app.config import DatabaseSettings
from app.db.images import ImageRepository
from app.db.tasks import TaskRepository


class Database:
    """Управляет пулом и репозиториями PostgreSQL."""

    def __init__(self, settings: DatabaseSettings) -> None:
        """Сохраняет настройки без открытия соединений."""
        self._settings = settings
        self._pool: Optional[asyncpg.Pool] = None
        self._tasks: Optional[TaskRepository] = None
        self._images: Optional[ImageRepository] = None

    @property
    def is_connected(self) -> bool:
        """Показывает состояние пула."""
        return self._pool is not None

    @property
    def pool(self) -> asyncpg.Pool:
        """Возвращает подключённый пул."""
        if self._pool is None:
            raise RuntimeError("Database is not connected")
        return self._pool

    @property
    def tasks(self) -> TaskRepository:
        """Возвращает репозиторий задач."""
        if self._tasks is None:
            raise RuntimeError("Database is not connected")
        return self._tasks

    @property
    def images(self) -> ImageRepository:
        """Возвращает репозиторий изображений."""
        if self._images is None:
            raise RuntimeError("Database is not connected")
        return self._images

    async def connect(self) -> None:
        """Открывает пул и создаёт репозитории."""
        if self._pool is not None:
            return

        pool = await asyncpg.create_pool(
            dsn=self._settings.dsn.get_secret_value(),
            min_size=self._settings.min_pool_size,
            max_size=self._settings.max_pool_size,
            command_timeout=self._settings.command_timeout,
        )

        self._pool = pool
        self._tasks = TaskRepository(pool)
        self._images = ImageRepository(pool)

    async def close(self) -> None:
        """Закрывает пул и очищает ссылки."""
        if self._pool is None:
            return

        try:
            await self._pool.close()
        finally:
            self._pool = None
            self._tasks = None
            self._images = None

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[asyncpg.Connection]:
        """Выдаёт одно соединение из пула."""
        async with self.pool.acquire() as connection:
            yield connection

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """Выдаёт соединение с активной транзакцией."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                yield connection
