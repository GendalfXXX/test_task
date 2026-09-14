from typing import Dict, List, Optional
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.task_queue.redis import RedisTaskQueue, TaskQueueError


class FakeRedis:
    """Имитирует списки Redis для тестов очереди."""

    def __init__(self) -> None:
        """Создаёт пустые списки."""
        self.lists: Dict[str, List[str]] = {}
        self.fail = False

    def _check(self) -> None:
        """Имитирует недоступность Redis."""
        if self.fail:
            raise RedisError("Redis is unavailable")

    async def lpush(self, name: str, value: str) -> int:
        """Добавляет значение слева."""
        self._check()
        values = self.lists.setdefault(name, [])
        values.insert(0, value)
        return len(values)

    async def brpoplpush(
        self,
        source: str,
        destination: str,
        timeout: int,
    ) -> Optional[str]:
        """Переносит значение справа налево."""
        self._check()
        values = self.lists.setdefault(source, [])
        if not values:
            return None
        value = values.pop()
        self.lists.setdefault(destination, []).insert(0, value)
        return value

    async def rpoplpush(
        self,
        source: str,
        destination: str,
    ) -> Optional[str]:
        """Переносит зарезервированное значение обратно."""
        return await self.brpoplpush(source, destination, 0)

    async def lrem(
        self,
        name: str,
        count: int,
        value: str,
    ) -> int:
        """Удаляет первое совпавшее значение."""
        self._check()
        values = self.lists.setdefault(name, [])
        if value not in values:
            return 0
        values.remove(value)
        return 1

    async def eval(
        self,
        script: str,
        key_count: int,
        processing: str,
        queue: str,
        value: str,
    ) -> int:
        """Имитирует атомарный возврат задачи."""
        removed = await self.lrem(processing, 1, value)
        if removed:
            self.lists.setdefault(queue, []).append(value)
        return removed


async def test_enqueue_and_reserve_are_fifo() -> None:
    """Проверяет FIFO и резервирование задачи."""
    client = FakeRedis()
    queue = RedisTaskQueue(client, "image_tasks")
    first = uuid4()
    second = uuid4()

    await queue.enqueue(first)
    await queue.enqueue(second)
    message = await queue.reserve()

    assert message is not None
    assert message.task_id == first
    assert client.lists["image_tasks:processing"] == [str(first)]


async def test_acknowledge_removes_reserved_message() -> None:
    """Проверяет подтверждение выполненной задачи."""
    client = FakeRedis()
    queue = RedisTaskQueue(client, "image_tasks")
    task_id = uuid4()
    await queue.enqueue(task_id)
    message = await queue.reserve()

    assert message is not None
    await queue.acknowledge(message)

    assert client.lists["image_tasks:processing"] == []


async def test_retry_returns_message_to_queue() -> None:
    """Проверяет возврат прерванной задачи."""
    client = FakeRedis()
    queue = RedisTaskQueue(client, "image_tasks")
    task_id = uuid4()
    await queue.enqueue(task_id)
    message = await queue.reserve()

    assert message is not None
    await queue.retry(message)
    retried = await queue.reserve()

    assert retried is not None
    assert retried.task_id == task_id


async def test_recovers_reserved_messages() -> None:
    """Проверяет восстановление резерва после перезапуска."""
    task_id = uuid4()
    client = FakeRedis()
    client.lists["image_tasks:processing"] = [str(task_id)]
    queue = RedisTaskQueue(client, "image_tasks")

    recovered = await queue.recover()
    message = await queue.reserve()

    assert recovered == 1
    assert message is not None
    assert message.task_id == task_id


async def test_rejects_invalid_identifier() -> None:
    """Проверяет удаление некорректного сообщения."""
    client = FakeRedis()
    client.lists["image_tasks"] = ["not-a-uuid"]
    queue = RedisTaskQueue(client, "image_tasks")

    with pytest.raises(TaskQueueError):
        await queue.reserve()

    assert client.lists["image_tasks:processing"] == []


async def test_wraps_redis_error() -> None:
    """Проверяет преобразование ошибки Redis."""
    client = FakeRedis()
    client.fail = True
    queue = RedisTaskQueue(client, "image_tasks")

    with pytest.raises(TaskQueueError):
        await queue.reserve()
