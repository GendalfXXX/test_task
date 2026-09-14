import json
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict
from uuid import UUID

from loguru import logger
from aiohttp import web
from pydantic import BaseModel, SecretStr

from app.config import LoggingSettings


SERIALIZED_KEY = "serialized"

STANDARD_CONTEXT_KEYS = {
    "duration_ms",
    "endpoint",
    "ip",
    "json",
    "method",
    "params",
    "request_id",
    "status_code",
}


def _json_default(value: Any) -> Any:
    """Преобразует нестандартные типы для JSON."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")

    if isinstance(value, SecretStr):
        return "***"

    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"

    if isinstance(value, (date, datetime, Path, UUID)):
        return str(value)

    return str(value)


def _format_traceback(record: Dict[str, Any]) -> Any:
    """Формирует traceback записи Loguru."""
    exception = record["exception"]
    if exception is None:
        return None

    return "".join(
        traceback.format_exception(
            exception.type,
            exception.value,
            exception.traceback,
        )
    )


def _serialize_record(record: Dict[str, Any]) -> None:
    """Собирает запись в требуемом JSONL-формате."""
    extra = record["extra"]

    context = {
        key: value
        for key, value in extra.items()
        if key not in STANDARD_CONTEXT_KEYS
        and key != SERIALIZED_KEY
    }

    payload = {
        "time": record["time"].isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "ip": extra.get("ip"),
        "endpoint": extra.get("endpoint"),
        "method": extra.get("method"),
        "request_id": extra.get("request_id"),
        "params": extra.get("params"),
        "json": extra.get("json"),
        "status_code": extra.get("status_code"),
        "duration_ms": extra.get("duration_ms"),
        "traceback": _format_traceback(record),
        "context": context or None,
    }

    extra[SERIALIZED_KEY] = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    )


def _json_formatter(_: Dict[str, Any]) -> str:
    """Возвращает шаблон сериализованной строки."""
    return "{extra[serialized]}\n"


def configure_logging(settings: LoggingSettings) -> None:
    """Настраивает включённые приёмники Loguru."""
    logger.remove()
    logger.configure(patcher=_serialize_record)

    if not settings.enabled:
        return

    common_options = {
        "level": settings.level,
        "format": _json_formatter,
        "colorize": False,
        "enqueue": True,
        "backtrace": False,
        "diagnose": False,
        "catch": True,
    }

    if settings.stdout:
        logger.add(
            sys.stdout,
            **common_options,
        )

    if settings.file:
        settings.file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        logger.add(
            str(settings.file_path),
            rotation=settings.rotation,
            retention=settings.retention,
            encoding="utf-8",
            **common_options,
        )


async def logging_context(
    _: web.Application,
) -> AsyncIterator[None]:
    """Завершает очередь логирования при остановке API."""
    try:
        yield
    finally:
        await logger.complete()
        logger.remove()
