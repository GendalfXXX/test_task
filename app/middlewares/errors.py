import json
from typing import Any, Dict, Optional

from aiohttp import web
from loguru import logger
from pydantic import ValidationError

from app.middlewares.logging import (
    LOG_JSON_KEY,
    LOG_PARAMS_KEY,
    REQUEST_LOGGER_KEY,
)
from app.middlewares.request_id import REQUEST_ID_KEY
from app.models.errors import ErrorDetails, ErrorResponse
from app.task_queue.redis import TaskQueueError


class APIError(Exception):
    """Описывает ожидаемую ошибку HTTP API."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Optional[Any] = None,
    ) -> None:
        """Сохраняет публичные параметры ошибки."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def error_response(
    request: web.Request,
    status: int,
    code: str,
    message: str,
    details: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
) -> web.Response:
    """Формирует единый JSON-ответ с ошибкой."""
    payload = ErrorResponse(
        error=ErrorDetails(
            code=code,
            message=message,
            request_id=request.get(REQUEST_ID_KEY, "unknown"),
            details=details,
        )
    )

    return web.json_response(
        payload.model_dump(mode="json", exclude_none=True),
        status=status,
        headers=headers,
    )


@web.middleware
async def error_middleware(
    request: web.Request,
    handler,
) -> web.StreamResponse:
    """Преобразует исключения в ответы API."""
    try:
        return await handler(request)

    except APIError as error:
        return error_response(
            request=request,
            status=error.status,
            code=error.code,
            message=error.message,
            details=error.details,
        )

    except ValidationError as error:
        details = [
            {
                "type": item["type"],
                "location": list(item["loc"]),
                "message": item["msg"],
            }
            for item in error.errors(
                include_input=False,
                include_url=False,
            )
        ]

        return error_response(
            request=request,
            status=422,
            code="validation_error",
            message="Request validation failed",
            details=details,
        )

    except json.JSONDecodeError as error:
        return error_response(
            request=request,
            status=400,
            code="invalid_json",
            message="Request body contains invalid JSON",
            details={
                "line": error.lineno,
                "column": error.colno,
            },
        )

    except web.HTTPException as error:
        excluded_headers = {
            "content-length",
            "content-type",
        }
        headers = {
            key: value
            for key, value in error.headers.items()
            if key.lower() not in excluded_headers
        }

        return error_response(
            request=request,
            status=error.status,
            code=f"http_{error.status}",
            message=error.reason,
            headers=headers,
        )

    except TaskQueueError as error:
        request_logger = request.get(REQUEST_LOGGER_KEY, logger)
        request_logger.bind(
            params=request.get(LOG_PARAMS_KEY),
            json=request.get(LOG_JSON_KEY),
        ).opt(exception=error).error("task_queue_unavailable")

        return error_response(
            request=request,
            status=503,
            code="task_queue_unavailable",
            message="Task queue is temporarily unavailable",
        )

    except Exception as error:
        request_logger = request.get(REQUEST_LOGGER_KEY, logger)

        request_logger.bind(
            params=request.get(LOG_PARAMS_KEY),
            json=request.get(LOG_JSON_KEY),
        ).opt(exception=error).error("unhandled_exception")

        return error_response(
            request=request,
            status=500,
            code="internal_error",
            message="Internal server error",
        )
