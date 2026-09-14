import csv
from io import StringIO
from typing import List

from aiohttp import web

from app.api.validation import (
    parse_image_list_query,
    parse_image_path,
    parse_image_upload,
    parse_resize_request,
)
from app.dependencies import get_image_service
from app.middlewares.errors import APIError
from app.middlewares.logging import add_log_parameters
from app.models.images import (
    ImageListFormat,
    ImageListResponse,
    ImageMetadata,
)
from app.models.tasks import TaskCreatedResponse


routes = web.RouteTableDef()

CSV_FIELDS = (
    "id",
    "original_filename",
    "media_type",
    "width",
    "height",
    "size_bytes",
    "quality",
    "created_at",
    "updated_at",
)


@routes.post("/api/images")
async def upload_image(request: web.Request) -> web.Response:
    """Принимает изображение и создаёт задачу обработки."""
    upload = await parse_image_upload(request)
    add_log_parameters(
        request,
        {
            "filename": upload.filename,
            "content_type": upload.content_type,
            "size_bytes": len(upload.content),
            "quality": upload.quality,
            "x": upload.x,
            "y": upload.y,
        },
    )

    service = get_image_service(request)
    task = await service.create_upload_task(upload)
    response = TaskCreatedResponse(
        task_id=task.id,
        status=task.status,
    )
    return web.json_response(
        response.model_dump(mode="json"),
        status=202,
    )


@routes.post("/api/images/resize")
async def resize_image(request: web.Request) -> web.Response:
    """Создаёт задачу изменения размеров изображения из БД."""
    resize = await parse_resize_request(request)

    service = get_image_service(request)
    task = await service.create_resize_task(resize)
    if task is None:
        raise APIError(
            status=404,
            code="image_not_found",
            message="Image not found",
        )

    response = TaskCreatedResponse(
        task_id=task.id,
        status=task.status,
    )
    return web.json_response(
        response.model_dump(mode="json"),
        status=202,
    )


@routes.get("/api/images")
async def list_images(request: web.Request) -> web.Response:
    """Возвращает параметры изображений в JSON или CSV."""
    query, limit = parse_image_list_query(request)

    service = get_image_service(request)
    images = await service.list_metadata(limit, query.offset)

    if query.format == ImageListFormat.CSV:
        return web.Response(
            text=_metadata_csv(images),
            content_type="text/csv",
            charset="utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="images.csv"'
                ),
            },
        )

    response = ImageListResponse(
        items=images,
        limit=limit,
        offset=query.offset,
    )
    return web.json_response(response.model_dump(mode="json"))


@routes.get("/api/images/{image_id}/metadata")
async def get_image_metadata(request: web.Request) -> web.Response:
    """Возвращает текущие параметры изображения."""
    path = parse_image_path(request)
    service = get_image_service(request)
    image = await service.get_metadata(path.image_id)

    if image is None:
        raise APIError(
            status=404,
            code="image_not_found",
            message="Image not found",
        )

    return web.json_response(image.model_dump(mode="json"))


@routes.get("/api/images/{image_id}")
async def get_image(request: web.Request) -> web.Response:
    """Возвращает бинарные данные изображения."""
    path = parse_image_path(request)
    service = get_image_service(request)
    image = await service.get_by_id(path.image_id)

    if image is None:
        raise APIError(
            status=404,
            code="image_not_found",
            message="Image not found",
        )

    return web.Response(
        body=image.content,
        content_type=image.media_type,
    )


def _metadata_csv(images: List[ImageMetadata]) -> str:
    """Сериализует параметры изображений в CSV."""
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()

    for image in images:
        writer.writerow(image.model_dump(mode="json"))

    return output.getvalue()
