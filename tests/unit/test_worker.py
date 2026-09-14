from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional
from uuid import UUID, uuid4

import pytest
from PIL import Image

from app.storage.filesystem import FileSystemStorage
from app.task_queue.redis import QueueMessage, TaskQueueError
from app.worker.consumer import (
    TaskProcessingError,
    TaskWorker,
)
from app.worker.processor import ImageProcessor


class FakeTaskRepository:
    """Имитирует переходы статуса задачи."""

    def __init__(self, row: Dict[str, Any]) -> None:
        """Сохраняет тестовую запись задачи."""
        self.row = row

    async def claim_pending(
        self,
        task_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Переводит задачу в обработку."""
        if self.row["id"] != task_id:
            return None
        if self.row["status"] not in {"pending", "processing"}:
            return None

        self.row["status"] = "processing"
        self.row["started_at"] = (
            self.row["started_at"]
            or datetime.now(timezone.utc)
        )
        return self.row

    async def get_by_id(
        self,
        task_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Возвращает тестовую задачу."""
        if self.row["id"] == task_id:
            return self.row
        return None

    async def complete(
        self,
        task_id: UUID,
        result_image_id: UUID,
        connection: object,
    ) -> bool:
        """Завершает задачу успешно."""
        if self.row["id"] != task_id:
            return False

        self.row["status"] = "completed"
        self.row["result_image_id"] = result_image_id
        self.row["finished_at"] = datetime.now(timezone.utc)
        return True

    async def fail(
        self,
        task_id: UUID,
        error_message: str,
    ) -> bool:
        """Завершает задачу с ошибкой."""
        if self.row["id"] != task_id:
            return False

        self.row["status"] = "failed"
        self.row["error_message"] = error_message
        self.row["finished_at"] = datetime.now(timezone.utc)
        return True


class FakeImageRepository:
    """Хранит результаты воркера в памяти."""

    def __init__(self) -> None:
        """Создаёт пустое хранилище."""
        self.rows: Dict[UUID, Dict[str, Any]] = {}

    async def create(
        self,
        image_id: UUID,
        content: bytes,
        original_filename: str,
        width: int,
        height: int,
        quality: Optional[int],
        connection: object,
    ) -> None:
        """Сохраняет тестовый JPEG."""
        now = datetime.now(timezone.utc)
        row = {
            "id": image_id,
            "content": content,
            "original_filename": original_filename,
            "media_type": "image/jpeg",
            "width": width,
            "height": height,
            "size_bytes": len(content),
            "quality": quality,
            "created_at": now,
            "updated_at": now,
        }
        self.rows[image_id] = row

    async def update(
        self,
        image_id: UUID,
        content: bytes,
        width: int,
        height: int,
        quality: Optional[int],
        connection: object,
    ) -> bool:
        """Обновляет тестовое изображение."""
        row = self.rows.get(image_id)
        if row is None:
            return False
        row.update(
            content=content,
            width=width,
            height=height,
            size_bytes=len(content),
            quality=quality,
            updated_at=datetime.now(timezone.utc),
        )
        return True

    async def get_by_id(
        self,
        image_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Возвращает тестовое изображение."""
        return self.rows.get(image_id)


class FakeDatabase:
    """Объединяет тестовые репозитории."""

    def __init__(self, task: Dict[str, Any]) -> None:
        """Создаёт репозитории для тестовой задачи."""
        self.tasks = FakeTaskRepository(task)
        self.images = FakeImageRepository()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[object]:
        """Имитирует транзакцию PostgreSQL."""
        yield object()



class FlakyQueue:
    """Имитирует временные сбои подтверждения Redis."""

    def __init__(
        self,
        acknowledge_failures: int,
        retry_failures: int,
    ) -> None:
        """Сохраняет число запланированных сбоев."""
        self.acknowledge_failures = acknowledge_failures
        self.retry_failures = retry_failures
        self.acknowledge_calls = 0
        self.retry_calls = 0

    async def acknowledge(self, _: QueueMessage) -> None:
        """Подтверждает сообщение после временных ошибок."""
        self.acknowledge_calls += 1
        if self.acknowledge_calls <= self.acknowledge_failures:
            raise TaskQueueError("Временный сбой ACK")

    async def retry(self, _: QueueMessage) -> None:
        """Возвращает сообщение после временных ошибок."""
        self.retry_calls += 1
        if self.retry_calls <= self.retry_failures:
            raise TaskQueueError("Временный сбой retry")


class FlakyStorage(FileSystemStorage):
    """Имитирует временную ошибку удаления файла."""

    def __init__(
        self,
        directory: Path,
        delete_failures: int,
    ) -> None:
        """Сохраняет число запланированных сбоев."""
        super().__init__(directory)
        self.delete_failures = delete_failures
        self.delete_calls = 0

    async def delete(self, stored_name: str) -> None:
        """Удаляет файл после временных ошибок."""
        self.delete_calls += 1
        if self.delete_calls <= self.delete_failures:
            raise OSError("Временный сбой удаления")
        await super().delete(stored_name)

@pytest.fixture
async def storage(tmp_path: Path) -> FileSystemStorage:
    """Создаёт временное файловое хранилище."""
    result = FileSystemStorage(tmp_path)
    await result.prepare()
    return result


async def test_completes_upload_task(
    storage: FileSystemStorage,
    tmp_path: Path,
) -> None:
    """Проверяет успешную конвертацию upload-задачи."""
    task_id = uuid4()
    source = BytesIO()
    Image.new("RGB", (8, 6), "green").save(
        source,
        format="PNG",
    )
    source_path = await storage.save_upload(
        task_id,
        source.getvalue(),
    )
    database = FakeDatabase(
        make_task(task_id, source_path=source_path)
    )
    worker = make_worker(database, storage)

    await worker.process_task(task_id)

    task = database.tasks.row
    assert task["status"] == "completed"
    image_id = task["result_image_id"]
    assert image_id in database.images.rows
    assert not (tmp_path / source_path).exists()

    image_row = database.images.rows[image_id]
    with Image.open(BytesIO(image_row["content"])) as image:
        assert image.format == "JPEG"
        assert image.size == (4, 3)


async def test_marks_invalid_image_as_failed(
    storage: FileSystemStorage,
    tmp_path: Path,
) -> None:
    """Проверяет завершение ошибочной задачи."""
    task_id = uuid4()
    source_path = await storage.save_upload(
        task_id,
        b"not-an-image",
    )
    database = FakeDatabase(
        make_task(task_id, source_path=source_path)
    )
    worker = make_worker(database, storage)

    await worker.process_task(task_id)

    task = database.tasks.row
    assert task["status"] == "failed"
    assert "UnidentifiedImageError" in task["error_message"]
    assert database.images.rows == {}
    assert not (tmp_path / source_path).exists()


async def test_removes_source_of_completed_recovered_task(
    storage: FileSystemStorage,
    tmp_path: Path,
) -> None:
    """Проверяет уборку исходника после аварийного перезапуска."""
    task_id = uuid4()
    source_path = await storage.save_upload(task_id, b"source")
    task = make_task(task_id, source_path=source_path)
    task["status"] = "completed"
    task["started_at"] = datetime.now(timezone.utc)
    task["finished_at"] = datetime.now(timezone.utc)
    task["result_image_id"] = uuid4()
    database = FakeDatabase(task)
    worker = make_worker(database, storage)

    await worker.process_task(task_id)

    assert not (tmp_path / source_path).exists()


async def test_resizes_image_from_database(
    storage: FileSystemStorage,
) -> None:
    """Проверяет resize-задачу с исходником из PostgreSQL."""
    task_id = uuid4()
    source_image_id = uuid4()
    database = FakeDatabase(
        make_task(
            task_id,
            task_type="resize",
            source_image_id=source_image_id,
            source_path=None,
        )
    )
    source = BytesIO()
    Image.new("RGB", (8, 6), "blue").save(
        source,
        format="JPEG",
    )
    now = datetime.now(timezone.utc)
    database.images.rows[source_image_id] = {
        "id": source_image_id,
        "content": source.getvalue(),
        "original_filename": "source.jpg",
        "media_type": "image/jpeg",
        "width": 8,
        "height": 6,
        "size_bytes": len(source.getvalue()),
        "quality": None,
        "created_at": now,
        "updated_at": now,
    }
    worker = make_worker(database, storage)

    await worker.process_task(task_id)

    result_id = database.tasks.row["result_image_id"]
    assert result_id == source_image_id
    result = database.images.rows[source_image_id]
    assert (result["width"], result["height"]) == (4, 3)
    assert len(database.images.rows) == 1



async def test_retries_redis_finalization(
    storage: FileSystemStorage,
) -> None:
    """Проверяет повтор ACK и возврата сообщения после сбоя Redis."""
    task_id = uuid4()
    database = FakeDatabase(
        make_task(task_id, source_path=None)
    )
    queue = FlakyQueue(
        acknowledge_failures=2,
        retry_failures=1,
    )
    worker = TaskWorker(
        database=database,
        queue=queue,
        storage=storage,
        processor=ImageProcessor(),
        retry_delay=0,
    )
    message = QueueMessage(
        task_id=task_id,
        raw_value=str(task_id),
    )

    await worker._acknowledge(message)
    await worker._retry_message(message)

    assert queue.acknowledge_calls == 3
    assert queue.retry_calls == 2


async def test_reconciles_source_cleanup_on_redelivery(
    storage: FileSystemStorage,
    tmp_path: Path,
) -> None:
    """Проверяет повторную уборку файла терминальной задачи."""
    task_id = uuid4()
    source_path = await storage.save_upload(task_id, b"source")
    task = make_task(task_id, source_path=source_path)
    task["status"] = "completed"
    task["started_at"] = datetime.now(timezone.utc)
    task["finished_at"] = datetime.now(timezone.utc)
    task["result_image_id"] = uuid4()
    database = FakeDatabase(task)
    flaky_storage = FlakyStorage(
        tmp_path,
        delete_failures=3,
    )
    worker = TaskWorker(
        database=database,
        queue=object(),
        storage=flaky_storage,
        processor=ImageProcessor(),
        retry_delay=0,
        cleanup_retry_attempts=3,
    )

    with pytest.raises(TaskProcessingError):
        await worker.process_task(task_id)

    assert (tmp_path / source_path).exists()

    await worker.process_task(task_id)

    assert flaky_storage.delete_calls == 4
    assert not (tmp_path / source_path).exists()

def make_worker(
    database: FakeDatabase,
    storage: FileSystemStorage,
) -> TaskWorker:
    """Создаёт воркер с тестовыми зависимостями."""
    return TaskWorker(
        database=database,
        queue=object(),
        storage=storage,
        processor=ImageProcessor(),
    )


def make_task(
    task_id: UUID,
    source_path: Optional[str],
    task_type: str = "upload",
    source_image_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Формирует ожидающую задачу."""
    now = datetime.now(timezone.utc)
    return {
        "id": task_id,
        "task_type": task_type,
        "status": "pending",
        "source_path": source_path,
        "original_filename": (
            "source.png"
            if task_type == "upload"
            else None
        ),
        "source_image_id": source_image_id,
        "result_image_id": None,
        "quality": 80 if task_type == "upload" else None,
        "target_width": 4,
        "target_height": 3,
        "error_message": None,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
    }
