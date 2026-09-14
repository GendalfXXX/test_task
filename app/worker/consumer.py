"""Получение и выполнение задач из Redis."""

import asyncio
from typing import Any, Tuple
from uuid import UUID, uuid4

from loguru import logger

from app.db.database import Database
from app.models.images import ProcessedImage, StoredImage
from app.models.tasks import TaskRecord, TaskStatus, TaskType
from app.task_queue.redis import (
    QueueMessage,
    RedisTaskQueue,
    TaskQueueError,
)
from app.storage.filesystem import FileSystemStorage
from app.worker.processor import ImageProcessor


class TaskProcessingError(RuntimeError):
    """Описывает ошибку выполнения задачи воркером."""


class TaskWorker:
    """Выполняет задачи обработки изображений."""

    def __init__(
        self,
        database: Database,
        queue: RedisTaskQueue,
        storage: FileSystemStorage,
        processor: ImageProcessor,
        poll_timeout: int = 1,
        retry_delay: float = 1.0,
        cleanup_retry_attempts: int = 3,
    ) -> None:
        """Сохраняет зависимости и интервалы ожидания."""
        if cleanup_retry_attempts <= 0:
            raise ValueError("Число попыток очистки должно быть положительным")

        self._database = database
        self._queue = queue
        self._storage = storage
        self._processor = processor
        self._poll_timeout = poll_timeout
        self._retry_delay = retry_delay
        self._cleanup_retry_attempts = cleanup_retry_attempts

    async def run_forever(self) -> None:
        """Ожидает задачи и последовательно выполняет их."""
        await self._recover_queue()
        logger.info("worker_started")

        while True:
            try:
                message = await self._queue.reserve(
                    timeout=self._poll_timeout
                )
            except TaskQueueError as error:
                logger.opt(exception=error).error(
                    "task_queue_read_failed"
                )
                await asyncio.sleep(self._retry_delay)
                continue

            if message is None:
                continue

            processing = asyncio.create_task(
                self.process_task(message.task_id)
            )
            try:
                # При остановке ждём текущую задачу: Pillow-поток
                # нельзя безопасно прервать посередине обработки.
                await asyncio.shield(processing)
            except asyncio.CancelledError as cancellation:
                logger.bind(task_id=message.task_id).info(
                    "worker_waits_for_current_task"
                )
                try:
                    await processing
                except Exception:
                    await self._retry_message(message)
                else:
                    await self._acknowledge(message)
                raise cancellation
            except Exception as error:
                logger.bind(task_id=message.task_id).opt(
                    exception=error
                ).error("task_processing_interrupted")
                await self._retry_message(message)
            else:
                await self._acknowledge(message)

    async def process_task(self, task_id: UUID) -> None:
        """Захватывает и выполняет одну ожидающую задачу."""
        row = await self._database.tasks.claim_pending(task_id)
        if row is None:
            await self._cleanup_terminal_upload(task_id)
            logger.bind(task_id=task_id).warning(
                "task_is_not_runnable"
            )
            return

        task = TaskRecord.model_validate(dict(row))
        terminal_status_saved = False
        result_image_id = task.source_image_id or uuid4()

        try:
            content, original_filename = await self._load_source(task)
            processed = await asyncio.to_thread(
                self._processor.convert_to_jpeg,
                content,
                task.quality,
                task.target_width,
                task.target_height,
            )

            async with self._database.transaction() as connection:
                await self._save_result(
                    task=task,
                    result_image_id=result_image_id,
                    processed=processed,
                    original_filename=original_filename,
                    connection=connection,
                )
                completed = await self._database.tasks.complete(
                    task_id=task.id,
                    result_image_id=result_image_id,
                    connection=connection,
                )
                if not completed:
                    raise TaskProcessingError(
                        "Не удалось завершить задачу"
                    )

            terminal_status_saved = True
        except Exception as error:
            error_message = self._error_message(error)
            terminal_status_saved = await self._database.tasks.fail(
                task_id=task.id,
                error_message=error_message,
            )
            logger.bind(
                task_id=task.id,
                task_type=task.task_type.value,
            ).opt(exception=error).error("task_failed")

            if not terminal_status_saved:
                raise TaskProcessingError(
                    "Не удалось сохранить ошибку задачи"
                ) from error
        else:
            logger.bind(
                task_id=task.id,
                image_id=result_image_id,
                task_type=task.task_type.value,
            ).info("task_completed")
        finally:
            if terminal_status_saved and task.source_path is not None:
                await self._delete_source(task)

    async def _cleanup_terminal_upload(
        self,
        task_id: UUID,
    ) -> None:
        """Удаляет исходник уже завершённой upload-задачи."""
        row = await self._database.tasks.get_by_id(task_id)
        if row is None:
            return

        task = TaskRecord.model_validate(dict(row))
        terminal_statuses = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
        }
        if (
            task.status in terminal_statuses
            and task.source_path is not None
        ):
            await self._delete_source(task)

    async def _save_result(
        self,
        task: TaskRecord,
        result_image_id: UUID,
        processed: ProcessedImage,
        original_filename: str,
        connection: Any,
    ) -> None:
        """Создаёт загрузку или обновляет редактируемое изображение."""
        if task.task_type == TaskType.UPLOAD:
            await self._database.images.create(
                image_id=result_image_id,
                content=processed.content,
                original_filename=original_filename,
                width=processed.width,
                height=processed.height,
                quality=processed.quality,
                connection=connection,
            )
            return

        updated = await self._database.images.update(
            image_id=result_image_id,
            content=processed.content,
            width=processed.width,
            height=processed.height,
            quality=processed.quality,
            connection=connection,
        )
        if not updated:
            raise TaskProcessingError(
                "Редактируемое изображение не найдено"
            )

    async def _recover_queue(self) -> None:
        """Восстанавливает зарезервированные задачи при старте."""
        while True:
            try:
                recovered = await self._queue.recover()
            except TaskQueueError as error:
                logger.opt(exception=error).error(
                    "task_queue_recovery_failed"
                )
                await asyncio.sleep(self._retry_delay)
                continue

            if recovered:
                logger.bind(count=recovered).warning(
                    "reserved_tasks_recovered"
                )
            return

    async def _acknowledge(self, message: QueueMessage) -> None:
        """Подтверждает обработанное сообщение Redis."""
        # Не берём следующую задачу, пока текущая не удалена из резерва.
        while True:
            try:
                await self._queue.acknowledge(message)
                return
            except TaskQueueError as error:
                logger.bind(task_id=message.task_id).opt(
                    exception=error
                ).error("task_acknowledge_failed")
                await asyncio.sleep(self._retry_delay)

    async def _retry_message(self, message: QueueMessage) -> None:
        """Возвращает прерванную задачу в Redis."""
        while True:
            try:
                await self._queue.retry(message)
                return
            except TaskQueueError as error:
                logger.bind(task_id=message.task_id).opt(
                    exception=error
                ).error("task_retry_failed")
                await asyncio.sleep(self._retry_delay)

    async def _load_source(
        self,
        task: TaskRecord,
    ) -> Tuple[bytes, str]:
        """Загружает исходник задачи из файла или PostgreSQL."""
        if task.task_type == TaskType.UPLOAD:
            if task.source_path is None or task.original_filename is None:
                raise TaskProcessingError(
                    "В upload-задаче отсутствует исходный файл"
                )
            content = await self._storage.read(task.source_path)
            return content, task.original_filename

        if task.task_type == TaskType.RESIZE:
            if task.source_image_id is None:
                raise TaskProcessingError(
                    "В resize-задаче отсутствует исходное изображение"
                )
            row = await self._database.images.get_by_id(
                task.source_image_id
            )
            if row is None:
                raise TaskProcessingError(
                    "Исходное изображение не найдено"
                )
            image = StoredImage.model_validate(dict(row))
            return image.content, image.original_filename

        raise TaskProcessingError("Неизвестный тип задачи")

    async def _delete_source(self, task: TaskRecord) -> None:
        """Удаляет обработанный исходный файл загрузки."""
        last_error = None
        # После исчерпания попыток сообщение вернётся в очередь
        # и при повторной доставке worker снова попробует удалить файл.
        for attempt in range(1, self._cleanup_retry_attempts + 1):
            try:
                await self._storage.delete(task.source_path or "")
                return
            except Exception as error:
                last_error = error
                logger.bind(
                    task_id=task.id,
                    attempt=attempt,
                    max_attempts=self._cleanup_retry_attempts,
                ).opt(exception=error).warning(
                    "source_file_delete_failed"
                )
                if attempt < self._cleanup_retry_attempts:
                    await asyncio.sleep(self._retry_delay)

        raise TaskProcessingError(
            "Не удалось удалить исходный файл задачи"
        ) from last_error

    @staticmethod
    def _error_message(error: Exception) -> str:
        """Формирует короткое сообщение для таблицы задач."""
        message = str(error).strip() or error.__class__.__name__
        return f"{error.__class__.__name__}: {message}"[:2000]
