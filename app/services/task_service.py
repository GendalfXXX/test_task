from typing import Optional
from uuid import UUID

from app.db.database import Database
from app.models.tasks import TaskRecord


class TaskService:
    """Предоставляет операции API над задачами."""

    def __init__(self, database: Database) -> None:
        """Сохраняет доступ к базе данных."""
        self._database = database

    async def get_by_id(
        self,
        task_id: UUID,
    ) -> Optional[TaskRecord]:
        """Возвращает задачу по идентификатору."""
        row = await self._database.tasks.get_by_id(task_id)
        if row is None:
            return None
        return TaskRecord.model_validate(dict(row))
