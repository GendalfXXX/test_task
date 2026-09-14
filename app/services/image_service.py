from typing import List, Optional
from uuid import UUID, uuid4

from loguru import logger

from app.db.database import Database
from app.models.images import (
    ImageMetadata,
    ImageResizeRequest,
    ImageUpload,
    StoredImage,
)
from app.models.tasks import TaskRecord
from app.task_queue.redis import RedisTaskQueue
from app.storage.filesystem import FileSystemStorage


class ImageService:
    """Оркестрирует операции API над изображениями."""

    def __init__(
        self,
        database: Database,
        queue: RedisTaskQueue,
        storage: FileSystemStorage,
    ) -> None:
        """Сохраняет зависимости сервиса."""
        self._database = database
        self._queue = queue
        self._storage = storage

    async def create_upload_task(
        self,
        upload: ImageUpload,
    ) -> TaskRecord:
        """Сохраняет загрузку и ставит задачу в очередь."""
        task_id = uuid4()
        source_path = None
        task_created = False

        try:
            source_path = await self._storage.save_upload(
                task_id=task_id,
                content=upload.content,
            )
            row = await self._database.tasks.create_upload(
                task_id=task_id,
                source_path=source_path,
                original_filename=upload.filename,
                quality=upload.quality,
                target_width=upload.x,
                target_height=upload.y,
            )
            task_created = True
            await self._queue.enqueue(task_id)
        except BaseException:
            # Компенсируем уже выполненные шаги при ошибке или отмене.
            await self._compensate_upload(
                task_id=task_id,
                task_created=task_created,
                source_path=source_path,
            )
            raise

        logger.bind(task_id=task_id).info("upload_task_created")
        return TaskRecord.model_validate(dict(row))

    async def get_by_id(
        self,
        image_id: UUID,
    ) -> Optional[StoredImage]:
        """Возвращает изображение с бинарными данными."""
        row = await self._database.images.get_by_id(image_id)
        if row is None:
            return None
        return StoredImage.model_validate(dict(row))

    async def create_resize_task(
        self,
        resize: ImageResizeRequest,
    ) -> Optional[TaskRecord]:
        """Ставит задачу изменения размеров существующего изображения."""
        source = await self._database.images.get_metadata_by_id(
            resize.image_id
        )
        if source is None:
            return None

        task_id = uuid4()
        task_created = False
        try:
            row = await self._database.tasks.create_resize(
                task_id=task_id,
                source_image_id=resize.image_id,
                target_width=resize.width,
                target_height=resize.height,
            )
            task_created = True
            await self._queue.enqueue(task_id)
        except BaseException:
            if task_created:
                await self._delete_pending_safely(task_id)
            raise

        logger.bind(
            task_id=task_id,
            image_id=resize.image_id,
        ).info("resize_task_created")
        return TaskRecord.model_validate(dict(row))

    async def get_metadata(
        self,
        image_id: UUID,
    ) -> Optional[ImageMetadata]:
        """Возвращает текущие параметры изображения."""
        row = await self._database.images.get_metadata_by_id(image_id)
        if row is None:
            return None
        return ImageMetadata.model_validate(dict(row))

    async def list_metadata(
        self,
        limit: int,
        offset: int,
    ) -> List[ImageMetadata]:
        """Возвращает страницу параметров изображений."""
        rows = await self._database.images.list_metadata(limit, offset)
        return [
            ImageMetadata.model_validate(dict(row))
            for row in rows
        ]

    async def _compensate_upload(
        self,
        task_id: UUID,
        task_created: bool,
        source_path: Optional[str],
    ) -> None:
        """Независимо удаляет задачу и загруженный файл."""
        if task_created:
            await self._delete_pending_safely(task_id)

        if source_path is None:
            return

        try:
            await self._storage.delete(source_path)
        except Exception as error:
            logger.bind(
                task_id=task_id,
                source_path=source_path,
            ).opt(exception=error).error(
                "upload_file_compensation_failed"
            )

    async def _delete_pending_safely(self, task_id: UUID) -> None:
        """Удаляет ожидающую задачу, не прерывая компенсацию."""
        try:
            await self._database.tasks.delete_pending(task_id)
        except Exception as error:
            logger.bind(task_id=task_id).opt(
                exception=error
            ).error("pending_task_compensation_failed")
