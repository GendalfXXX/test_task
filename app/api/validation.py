import json
from typing import Any, Dict, Optional, Tuple, Type, TypeVar

from aiohttp import hdrs, web
from aiohttp.multipart import BodyPartReader
from pydantic import BaseModel

from app.dependencies import SETTINGS_KEY
from app.middlewares.errors import APIError
from app.middlewares.logging import set_log_json
from app.models.images import (
    ImageListQuery,
    ImagePath,
    ImageResizeRequest,
    ImageUpload,
)
from app.models.logs import LogQuery
from app.models.tasks import TaskPath


UPLOAD_FIELDS = {"file", "quality", "x", "y"}
ModelType = TypeVar("ModelType", bound=BaseModel)


async def parse_image_upload(request: web.Request) -> ImageUpload:
    """Проверяет multipart-загрузку изображения."""
    if request.content_type != "multipart/form-data":
        raise APIError(
            status=415,
            code="unsupported_media_type",
            message="Content-Type must be multipart/form-data",
        )

    reader = await request.multipart()
    values: Dict[str, Any] = {}
    seen_fields = set()

    while True:
        part = await reader.next()
        if part is None:
            break

        field_name = part.name
        if field_name not in UPLOAD_FIELDS:
            raise APIError(
                status=400,
                code="unexpected_field",
                message=f"Unexpected multipart field: {field_name}",
            )
        if field_name in seen_fields:
            raise APIError(
                status=400,
                code="duplicate_field",
                message=f"Multipart field is duplicated: {field_name}",
            )
        seen_fields.add(field_name)

        if field_name == "file":
            filename = (part.filename or "").strip()
            media_type = (
                part.headers.get(hdrs.CONTENT_TYPE, "")
                .split(";", maxsplit=1)[0]
                .strip()
                .lower()
            )
            if not filename:
                raise APIError(
                    status=400,
                    code="missing_filename",
                    message="Image filename is required",
                )
            if not media_type.startswith("image/"):
                raise APIError(
                    status=415,
                    code="invalid_image_content_type",
                    message="Uploaded file must have an image content type",
                )

            values["filename"] = filename
            values["content_type"] = media_type
            values["content"] = await _read_file(
                part,
                request.app[SETTINGS_KEY].api.max_upload_size_bytes,
            )
            continue

        if part.filename is not None:
            raise APIError(
                status=400,
                code="invalid_parameter",
                message=f"{field_name} must be a text field",
            )
        values[field_name] = await _read_text_parameter(part)

    if "file" not in seen_fields:
        raise APIError(
            status=400,
            code="missing_file",
            message="Multipart field 'file' is required",
        )

    upload = ImageUpload.model_validate(values)
    settings = request.app[SETTINGS_KEY].api
    _validate_dimensions(
        upload.x,
        upload.y,
        settings.max_image_dimension,
        settings.max_image_pixels,
    )
    return upload


async def _read_file(
    part: BodyPartReader,
    max_size: int,
) -> bytes:
    """Читает файл частями и ограничивает потребление памяти."""
    content = bytearray()

    while True:
        chunk = await part.read_chunk(size=64 * 1024)
        if not chunk:
            break
        if len(content) + len(chunk) > max_size:
            raise APIError(
                status=413,
                code="image_too_large",
                message=f"Image must not exceed {max_size} bytes",
            )
        content.extend(chunk)

    return bytes(content)


async def _read_text_parameter(part: BodyPartReader) -> str:
    """Читает короткий текстовый параметр multipart."""
    content = bytearray()

    while True:
        chunk = await part.read_chunk(size=64)
        if not chunk:
            break
        if len(content) + len(chunk) > 64:
            raise APIError(
                status=400,
                code="parameter_too_large",
                message="Multipart text parameter is too large",
            )
        content.extend(chunk)

    try:
        return bytes(content).decode(
            part.get_charset(default="utf-8")
        )
    except UnicodeDecodeError as error:
        raise APIError(
            status=400,
            code="invalid_parameter_encoding",
            message="Multipart text parameter must be UTF-8",
        ) from error


async def parse_json_model(
    request: web.Request,
    model: Type[ModelType],
) -> ModelType:
    """Читает JSON и проверяет его Pydantic-моделью."""
    content_type = request.content_type.lower()
    if (
        content_type != "application/json"
        and not content_type.endswith("+json")
    ):
        raise APIError(
            status=415,
            code="unsupported_media_type",
            message="Content-Type must be application/json",
        )

    try:
        payload = await request.json(loads=json.loads)
    except UnicodeDecodeError as error:
        set_log_json(request, {"_invalid_json": True})
        raise APIError(
            status=400,
            code="invalid_json",
            message="Request body contains invalid JSON",
        ) from error
    except json.JSONDecodeError:
        set_log_json(request, {"_invalid_json": True})
        raise
    except web.HTTPException:
        set_log_json(request, {"_body_unavailable": True})
        raise

    set_log_json(request, payload)
    return model.model_validate(payload)


async def parse_resize_request(
    request: web.Request,
) -> ImageResizeRequest:
    """Читает и проверяет параметры изменения размера."""
    resize = await parse_json_model(request, ImageResizeRequest)
    settings = request.app[SETTINGS_KEY].api
    _validate_dimensions(
        resize.width,
        resize.height,
        settings.max_image_dimension,
        settings.max_image_pixels,
    )
    return resize


def parse_image_list_query(
    request: web.Request,
) -> Tuple[ImageListQuery, int]:
    """Проверяет параметры списка изображений."""
    query = ImageListQuery.model_validate(dict(request.query))
    configured_limit = request.app[SETTINGS_KEY].api.image_list_limit
    limit = query.limit or configured_limit
    if limit > configured_limit:
        raise APIError(
            status=422,
            code="list_limit_too_large",
            message=f"Limit must not exceed {configured_limit}",
        )
    return query, limit


def parse_log_limit(request: web.Request) -> int:
    """Проверяет параметры чтения логов."""
    query = LogQuery.model_validate(dict(request.query))
    settings = request.app[SETTINGS_KEY].logging
    limit = query.limit or settings.read_limit
    if limit > settings.max_read_limit:
        raise APIError(
            status=422,
            code="log_limit_too_large",
            message=(
                "Log limit must not exceed "
                f"{settings.max_read_limit}"
            ),
        )
    return limit


def parse_image_path(request: web.Request) -> ImagePath:
    """Проверяет идентификатор изображения в пути."""
    return ImagePath.model_validate(request.match_info)


def parse_task_path(request: web.Request) -> TaskPath:
    """Проверяет идентификатор задачи в пути."""
    return TaskPath.model_validate(request.match_info)


def _validate_dimensions(
    width: Optional[int],
    height: Optional[int],
    max_dimension: int,
    max_pixels: int,
) -> None:
    """Проверяет стороны и общее число запрошенных пикселей."""
    dimensions = [
        value
        for value in (width, height)
        if value is not None
    ]
    if dimensions and max(dimensions) > max_dimension:
        raise APIError(
            status=422,
            code="image_dimension_too_large",
            message=(
                "Image dimensions must not exceed "
                f"{max_dimension} pixels"
            ),
        )

    if (
        width is not None
        and height is not None
        and width * height > max_pixels
    ):
        raise APIError(
            status=422,
            code="image_pixel_count_too_large",
            message=(
                "Image pixel count must not exceed "
                f"{max_pixels}"
            ),
        )
