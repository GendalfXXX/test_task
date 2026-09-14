import asyncio
from collections.abc import Mapping
from time import perf_counter
from typing import Any, Awaitable, Callable, Dict

from aiohttp import web
from loguru import logger

from app.middlewares.request_id import REQUEST_ID_KEY


REQUEST_LOGGER_KEY = web.RequestKey("request_logger")
LOG_PARAMS_KEY = web.RequestKey("log_params")
LOG_JSON_KEY = web.RequestKey("log_json")

Handler = Callable[
    [web.Request],
    Awaitable[web.StreamResponse],
]

SENSITIVE_KEYS = {
    "authorization",
    "bearer_token",
    "password",
    "postgres_dsn",
    "redis_dsn",
    "secret",
    "token",
}


def _redact(value: Any) -> Any:
    """Скрывает чувствительные значения во вложенных данных."""
    if isinstance(value, Mapping):
        return {
            str(key): (
                "***"
                if str(key).lower() in SENSITIVE_KEYS
                else _redact(item)
            )
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [_redact(item) for item in value]

    if isinstance(value, tuple):
        return [_redact(item) for item in value]

    return value


def _query_parameters(request: web.Request) -> Dict[str, Any]:
    """Собирает query-параметры без потери повторов."""
    result: Dict[str, Any] = {}

    for key in request.query:
        if key in result:
            continue

        values = request.query.getall(key)
        result[key] = values[0] if len(values) == 1 else values

    return result


def add_log_parameters(
    request: web.Request,
    parameters: Mapping[str, Any],
) -> None:
    """Добавляет безопасные параметры тела в контекст лога."""
    current = request.get(LOG_PARAMS_KEY, {})
    current["body"] = _redact(dict(parameters))
    request[LOG_PARAMS_KEY] = current


def set_log_json(request: web.Request, payload: Any) -> None:
    """Добавляет безопасный JSON в контекст лога."""
    request[LOG_JSON_KEY] = _redact(payload)


@web.middleware
async def logging_middleware(
    request: web.Request,
    handler: Handler,
) -> web.StreamResponse:
    """Записывает результат и длительность HTTP-запроса."""
    request_id = request[REQUEST_ID_KEY]

    request[LOG_PARAMS_KEY] = {
        "path": _redact(dict(request.match_info)),
        "query": _redact(_query_parameters(request)),
    }
    request[LOG_JSON_KEY] = None

    request_logger = logger.bind(
        request_id=request_id,
        ip=request.remote,
        endpoint=request.path,
        method=request.method,
    )
    request[REQUEST_LOGGER_KEY] = request_logger

    started_at = perf_counter()

    try:
        response = await handler(request)
    except asyncio.CancelledError:
        duration_ms = round((perf_counter() - started_at) * 1000, 3)
        request_logger.bind(
            params=request[LOG_PARAMS_KEY],
            json=request[LOG_JSON_KEY],
            status_code=499,
            duration_ms=duration_ms,
        ).warning("request_cancelled")
        raise

    duration_ms = round((perf_counter() - started_at) * 1000, 3)

    request_logger.bind(
        params=request[LOG_PARAMS_KEY],
        json=request[LOG_JSON_KEY],
        status_code=response.status,
        duration_ms=duration_ms,
    ).info("request_completed")

    return response
