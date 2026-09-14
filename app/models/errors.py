from typing import Any, Optional

from pydantic import BaseModel


class ErrorDetails(BaseModel):
    """Описывает детали ошибки API."""

    code: str
    message: str
    request_id: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    """Описывает единый ответ с ошибкой."""

    error: ErrorDetails
