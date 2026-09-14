from typing import List, Optional
from uuid import UUID

import asyncpg

from app.db.base import BaseRepository


class ImageRepository(BaseRepository):
    """Выполняет SQL-запросы к таблице изображений."""

    async def create(
        self,
        image_id: UUID,
        content: bytes,
        original_filename: str,
        width: int,
        height: int,
        quality: Optional[int],
        connection: Optional[asyncpg.Connection] = None,
    ) -> None:
        """Сохраняет JPEG в базе данных."""
        executor = self.executor(connection)
        await executor.execute(
            """
            INSERT INTO images (
                id,
                content,
                original_filename,
                media_type,
                width,
                height,
                size_bytes,
                quality
            )
            VALUES ($1, $2, $3, 'image/jpeg', $4, $5, $6, $7)
            """,
            image_id,
            content,
            original_filename,
            width,
            height,
            len(content),
            quality,
        )

    async def update(
        self,
        image_id: UUID,
        content: bytes,
        width: int,
        height: int,
        quality: Optional[int],
        connection: Optional[asyncpg.Connection] = None,
    ) -> bool:
        """Обновляет содержимое и параметры изображения."""
        executor = self.executor(connection)
        updated_id = await executor.fetchval(
            """
            UPDATE images
            SET
                content = $2,
                width = $3,
                height = $4,
                size_bytes = $5,
                quality = $6
            WHERE id = $1
            RETURNING id
            """,
            image_id,
            content,
            width,
            height,
            len(content),
            quality,
        )
        return updated_id is not None

    async def get_metadata_by_id(
        self,
        image_id: UUID,
        connection: Optional[asyncpg.Connection] = None,
    ) -> Optional[asyncpg.Record]:
        """Возвращает параметры изображения без бинарных данных."""
        executor = self.executor(connection)
        return await executor.fetchrow(
            """
            SELECT
                id,
                original_filename,
                media_type,
                width,
                height,
                size_bytes,
                quality,
                created_at,
                updated_at
            FROM images
            WHERE id = $1
            """,
            image_id,
        )

    async def list_metadata(
        self,
        limit: int,
        offset: int,
        connection: Optional[asyncpg.Connection] = None,
    ) -> List[asyncpg.Record]:
        """Возвращает страницу параметров изображений."""
        executor = self.executor(connection)
        return await executor.fetch(
            """
            SELECT
                id,
                original_filename,
                media_type,
                width,
                height,
                size_bytes,
                quality,
                created_at,
                updated_at
            FROM images
            ORDER BY created_at DESC, id DESC
            LIMIT $1
            OFFSET $2
            """,
            limit,
            offset,
        )

    async def get_by_id(
        self,
        image_id: UUID,
        connection: Optional[asyncpg.Connection] = None,
    ) -> Optional[asyncpg.Record]:
        """Возвращает изображение по идентификатору."""
        executor = self.executor(connection)
        return await executor.fetchrow(
            """
            SELECT
                id,
                content,
                original_filename,
                media_type,
                width,
                height,
                size_bytes,
                quality,
                created_at,
                updated_at
            FROM images
            WHERE id = $1
            """,
            image_id,
        )
