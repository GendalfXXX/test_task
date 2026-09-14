from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class TaskType(str, Enum):
    """Перечисляет типы фоновых задач."""

    UPLOAD = "upload"
    RESIZE = "resize"


class TaskStatus(str, Enum):
    """Перечисляет состояния фоновой задачи."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPath(BaseModel):
    """Проверяет идентификатор задачи в пути."""

    task_id: UUID


class TaskRecord(BaseModel):
    """Описывает полную запись задачи."""

    id: UUID
    task_type: TaskType
    status: TaskStatus
    source_path: Optional[str]
    original_filename: Optional[str]
    source_image_id: Optional[UUID]
    result_image_id: Optional[UUID]
    quality: Optional[int]
    target_width: Optional[int]
    target_height: Optional[int]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class TaskCreatedResponse(BaseModel):
    """Описывает ответ после постановки задачи."""

    task_id: UUID
    status: TaskStatus


class TaskStatusResponse(BaseModel):
    """Описывает публичный статус задачи."""

    task_id: UUID
    status: TaskStatus
    image_id: Optional[UUID] = None
    error: Optional[str] = None
