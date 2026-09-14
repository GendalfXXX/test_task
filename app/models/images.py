from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ImageUpload(BaseModel):
    """Описывает загруженный файл и параметры обработки."""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(pattern=r"^image/")
    content: bytes = Field(min_length=1)
    quality: Optional[int] = Field(default=None, ge=1, le=100)
    x: Optional[int] = Field(default=None, gt=0)
    y: Optional[int] = Field(default=None, gt=0)


class ImagePath(BaseModel):
    """Проверяет идентификатор изображения в пути."""

    image_id: UUID


class ImageResizeRequest(BaseModel):
    """Описывает задачу изменения размеров изображения."""

    image_id: UUID
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ImageListFormat(str, Enum):
    """Перечисляет форматы списка изображений."""

    JSON = "json"
    CSV = "csv"


class ImageListQuery(BaseModel):
    """Проверяет параметры списка изображений."""

    format: ImageListFormat = ImageListFormat.JSON
    limit: Optional[int] = Field(default=None, gt=0)
    offset: int = Field(default=0, ge=0)


class StoredImage(BaseModel):
    """Описывает сохранённое JPEG-изображение."""

    id: UUID
    content: bytes
    original_filename: str
    media_type: str
    width: int
    height: int
    size_bytes: int
    quality: Optional[int]
    created_at: datetime
    updated_at: datetime


class ImageMetadata(BaseModel):
    """Описывает параметры изображения без бинарных данных."""

    id: UUID
    original_filename: str
    media_type: str
    width: int
    height: int
    size_bytes: int
    quality: Optional[int]
    created_at: datetime
    updated_at: datetime


class ImageListResponse(BaseModel):
    """Описывает страницу списка изображений."""

    items: List[ImageMetadata]
    limit: int
    offset: int


class ProcessedImage(BaseModel):
    """Хранит результат обработки изображения в памяти."""

    content: bytes
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    size_bytes: int = Field(gt=0)
    quality: Optional[int] = Field(default=None, ge=1, le=100)

