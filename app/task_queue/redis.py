from dataclasses import dataclass
from typing import AsyncIterator, Optional
from uuid import UUID

from aiohttp import web
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.dependencies import REDIS_KEY, SETTINGS_KEY


class TaskQueueError(RuntimeError):
    """Описывает ошибку взаимодействия с очередью Redis."""


@dataclass(frozen=True)
class QueueMessage:
    """Хранит зарезервированное сообщение Redis."""

    task_id: UUID
    raw_value: str


class RedisTaskQueue:
    """Передаёт задачи через подтверждаемую очередь Redis."""

    def __init__(self, client: Redis, queue_name: str) -> None:
        """Сохраняет Redis-клиент и имена списков."""
        self._client = client
        self._queue_name = queue_name
        self._processing_name = f"{queue_name}:processing"

    async def enqueue(self, task_id: UUID) -> None:
        """Добавляет идентификатор задачи в очередь."""
        try:
            # В Redis передаём только ID.
            # Остальные данные остаются в PostgreSQL.
            await self._client.lpush(self._queue_name, str(task_id))
        except RedisError as error:
            raise TaskQueueError(
                "Не удалось добавить задачу в Redis"
            ) from error

    async def reserve(
        self,
        timeout: int = 1,
    ) -> Optional[QueueMessage]:
        """Атомарно переносит задачу в список обработки."""
        try:
            value = await self._client.brpoplpush(
                self._queue_name,
                self._processing_name,
                timeout=timeout,
            )
            if value is None:
                return None

            try:
                task_id = UUID(value)
            except (TypeError, ValueError) as error:
                await self._client.lrem(
                    self._processing_name,
                    1,
                    value,
                )
                raise TaskQueueError(
                    "Redis вернул некорректный идентификатор задачи"
                ) from error
        except TaskQueueError:
            raise
        except RedisError as error:
            raise TaskQueueError(
                "Не удалось получить задачу из Redis"
            ) from error

        return QueueMessage(task_id=task_id, raw_value=value)

    async def acknowledge(self, message: QueueMessage) -> None:
        """Удаляет успешно обработанную задачу из резерва."""
        try:
            await self._client.lrem(
                self._processing_name,
                1,
                message.raw_value,
            )
        except RedisError as error:
            raise TaskQueueError(
                "Не удалось подтвердить задачу в Redis"
            ) from error

    async def retry(self, message: QueueMessage) -> None:
        """Возвращает незавершённую задачу в основную очередь."""
        script = """
        if redis.call('LREM', KEYS[1], 1, ARGV[1]) > 0 then
            return redis.call('RPUSH', KEYS[2], ARGV[1])
        end
        return 0
        """
        try:
            await self._client.eval(
                script,
                2,
                self._processing_name,
                self._queue_name,
                message.raw_value,
            )
        except RedisError as error:
            raise TaskQueueError(
                "Не удалось вернуть задачу в Redis"
            ) from error

    async def recover(self) -> int:
        """Возвращает незавершённые задачи после перезапуска."""
        recovered = 0
        try:
            while True:
                value = await self._client.rpoplpush(
                    self._processing_name,
                    self._queue_name,
                )
                if value is None:
                    return recovered
                recovered += 1
        except RedisError as error:
            raise TaskQueueError(
                "Не удалось восстановить задачи Redis"
            ) from error


async def redis_context(
    app: web.Application,
) -> AsyncIterator[None]:
    """Управляет Redis-клиентом."""
    settings = app[SETTINGS_KEY].redis
    client = Redis.from_url(
        settings.dsn.get_secret_value(),
        decode_responses=True,
    )

    try:
        await client.ping()
        app[REDIS_KEY] = client
        yield
    finally:
        await client.aclose()
