from typing import Optional
from uuid import UUID

import asyncpg

from app.db.base import BaseRepository


class TaskRepository(BaseRepository):
    """Выполняет SQL-запросы к таблице задач."""

    async def create_upload(
        self,
        task_id: UUID,
        source_path: str,
        original_filename: str,
        quality: Optional[int],
        target_width: Optional[int],
        target_height: Optional[int],
        connection: Optional[asyncpg.Connection] = None,
    ) -> asyncpg.Record:
        """Создаёт задачу обработки загруженного файла."""
        executor = self.executor(connection)
        return await executor.fetchrow(
            """
            INSERT INTO tasks (
                id,
                task_type,
                source_path,
                original_filename,
                quality,
                target_width,
                target_height
            )
            VALUES ($1, 'upload', $2, $3, $4, $5, $6)
            RETURNING
                id,
                task_type,
                status,
                source_path,
                original_filename,
                source_image_id,
                result_image_id,
                quality,
                target_width,
                target_height,
                error_message,
                created_at,
                updated_at,
                started_at,
                finished_at
            """,
            task_id,
            source_path,
            original_filename,
            quality,
            target_width,
            target_height,
        )

    async def create_resize(
        self,
        task_id: UUID,
        source_image_id: UUID,
        target_width: int,
        target_height: int,
        connection: Optional[asyncpg.Connection] = None,
    ) -> asyncpg.Record:
        """Создаёт задачу изменения размеров изображения."""
        executor = self.executor(connection)
        return await executor.fetchrow(
            """
            INSERT INTO tasks (
                id,
                task_type,
                source_image_id,
                target_width,
                target_height
            )
            VALUES ($1, 'resize', $2, $3, $4)
            RETURNING
                id,
                task_type,
                status,
                source_path,
                original_filename,
                source_image_id,
                result_image_id,
                quality,
                target_width,
                target_height,
                error_message,
                created_at,
                updated_at,
                started_at,
                finished_at
            """,
            task_id,
            source_image_id,
            target_width,
            target_height,
        )

    async def get_by_id(
        self,
        task_id: UUID,
        connection: Optional[asyncpg.Connection] = None,
    ) -> Optional[asyncpg.Record]:
        """Возвращает задачу по идентификатору."""
        executor = self.executor(connection)
        return await executor.fetchrow(
            """
            SELECT
                id,
                task_type,
                status,
                source_path,
                original_filename,
                source_image_id,
                result_image_id,
                quality,
                target_width,
                target_height,
                error_message,
                created_at,
                updated_at,
                started_at,
                finished_at
            FROM tasks
            WHERE id = $1
            """,
            task_id,
        )

    async def delete_pending(
        self,
        task_id: UUID,
        connection: Optional[asyncpg.Connection] = None,
    ) -> None:
        """Удаляет задачу, ещё не взятую воркером."""
        executor = self.executor(connection)
        await executor.execute(
            """
            DELETE FROM tasks
            WHERE id = $1
              AND status = 'pending'
            """,
            task_id,
        )

    async def claim_pending(
        self,
        task_id: UUID,
        connection: Optional[asyncpg.Connection] = None,
    ) -> Optional[asyncpg.Record]:
        """Атомарно захватывает новую или восстановленную задачу."""
        executor = self.executor(connection)
        return await executor.fetchrow(
            """
            UPDATE tasks
            SET
                status = 'processing',
                started_at = COALESCE(started_at, NOW())
            WHERE id = $1
              AND status IN ('pending', 'processing')
            RETURNING
                id,
                task_type,
                status,
                source_path,
                original_filename,
                source_image_id,
                result_image_id,
                quality,
                target_width,
                target_height,
                error_message,
                created_at,
                updated_at,
                started_at,
                finished_at
            """,
            task_id,
        )

    async def complete(
        self,
        task_id: UUID,
        result_image_id: UUID,
        connection: Optional[asyncpg.Connection] = None,
    ) -> bool:
        """Завершает задачу и связывает её с результатом."""
        executor = self.executor(connection)
        updated_id = await executor.fetchval(
            """
            UPDATE tasks
            SET
                status = 'completed',
                result_image_id = $2,
                finished_at = NOW()
            WHERE id = $1
              AND status = 'processing'
            RETURNING id
            """,
            task_id,
            result_image_id,
        )
        return updated_id is not None

    async def fail(
        self,
        task_id: UUID,
        error_message: str,
        connection: Optional[asyncpg.Connection] = None,
    ) -> bool:
        """Завершает задачу с ошибкой обработки."""
        executor = self.executor(connection)
        updated_id = await executor.fetchval(
            """
            UPDATE tasks
            SET
                status = 'failed',
                error_message = $2,
                finished_at = NOW()
            WHERE id = $1
              AND status = 'processing'
            RETURNING id
            """,
            task_id,
            error_message,
        )
        return updated_id is not None
