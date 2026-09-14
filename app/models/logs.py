from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LogQuery(BaseModel):
    """Проверяет параметры чтения логов."""

    limit: Optional[int] = Field(default=None, gt=0)


class LogListResponse(BaseModel):
    """Описывает последние записи JSONL-лога."""

    items: List[Dict[str, Any]]
    limit: int


