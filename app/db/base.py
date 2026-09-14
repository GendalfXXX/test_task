from typing import Optional, Union

import asyncpg


DatabaseExecutor = Union[asyncpg.Pool, asyncpg.Connection]


class BaseRepository:
    """Выбирает пул или переданное соединение для SQL."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Сохраняет общий пул соединений."""
        self._pool = pool

    def executor(
        self,
        connection: Optional[asyncpg.Connection] = None,
    ) -> DatabaseExecutor:
        """Возвращает исполнитель SQL-запроса."""
        return connection if connection is not None else self._pool
