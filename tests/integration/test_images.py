import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
from uuid import UUID, uuid4

from aiohttp import FormData

from tests.integration.support import ApiContext


def store_image(
    context: ApiContext,
    filename: str = "sample.png",
) -> UUID:
    """Добавляет изображение в тестовую БД."""
    image_id = uuid4()
    now = datetime.now(timezone.utc)
    content = b"stored-jpeg-content"
    context.database.images.rows[image_id] = {
        "id": image_id,
        "content": content,
        "original_filename": filename,
        "media_type": "image/jpeg",
        "width": 640,
        "height": 480,
        "size_bytes": len(content),
        "quality": 80,
        "created_at": now,
        "updated_at": now,
    }
    return image_id


async def test_upload_creates_task_file_and_queue_message(
    api_context: ApiContext,
) -> None:
    """Проверяет полную HTTP-цепочку создания upload-задачи."""
    image_content = b"fake-png-content"
    form = FormData()
    form.add_field(
        "file",
        image_content,
        filename="sample.png",
        content_type="image/png",
    )
    form.add_field("quality", "80")
    form.add_field("x", "640")
    form.add_field("y", "480")

    response = await api_context.client.post(
        "/api/images",
        data=form,
        headers=api_context.auth_headers,
    )

    assert response.status == 202
    payload = await response.json()
    task_id = UUID(payload["task_id"])
    assert payload["status"] == "pending"

    task = api_context.database.tasks.rows[task_id]
    assert task["quality"] == 80
    assert task["target_width"] == 640
    assert task["target_height"] == 480
    assert api_context.redis.items == [
        ("image_tasks", str(task_id))
    ]
    assert (
        api_context.storage_path / task["source_path"]
    ).read_bytes() == image_content


async def test_upload_rejects_non_image_content_type(
    api_context: ApiContext,
) -> None:
    """Проверяет отказ для не-графического Content-Type."""
    form = FormData()
    form.add_field(
        "file",
        b"plain text",
        filename="sample.txt",
        content_type="text/plain",
    )

    response = await api_context.client.post(
        "/api/images",
        data=form,
        headers=api_context.auth_headers,
    )

    assert response.status == 415
    assert api_context.redis.items == []


async def test_upload_rejects_invalid_quality(
    api_context: ApiContext,
) -> None:
    """Проверяет валидацию качества изображения."""
    form = FormData()
    form.add_field(
        "file",
        b"fake-jpeg-content",
        filename="sample.jpg",
        content_type="image/jpeg",
    )
    form.add_field("quality", "101")

    response = await api_context.client.post(
        "/api/images",
        data=form,
        headers=api_context.auth_headers,
    )

    assert response.status == 422
    assert api_context.redis.items == []


async def test_upload_rejects_large_dimension(
    api_context: ApiContext,
) -> None:
    """Проверяет настроенный предел размеров изображения."""
    form = FormData()
    form.add_field(
        "file",
        b"fake-jpeg-content",
        filename="sample.jpg",
        content_type="image/jpeg",
    )
    form.add_field("x", "10001")

    response = await api_context.client.post(
        "/api/images",
        data=form,
        headers=api_context.auth_headers,
    )

    assert response.status == 422
    assert api_context.redis.items == []


async def test_upload_rejects_file_over_configured_limit(
    api_context: ApiContext,
) -> None:
    """Проверяет ограничение размера загружаемого файла."""
    form = FormData()
    form.add_field(
        "file",
        BytesIO(b"x" * (1024 * 1024 + 1)),
        filename="large.jpg",
        content_type="image/jpeg",
    )

    response = await api_context.client.post(
        "/api/images",
        data=form,
        headers=api_context.auth_headers,
    )

    assert response.status == 413
    assert api_context.database.tasks.rows == {}


async def test_queue_failure_removes_task_and_file(
    api_context: ApiContext,
) -> None:
    """Проверяет компенсацию при недоступности Redis."""
    api_context.redis.fail = True
    form = FormData()
    form.add_field(
        "file",
        b"fake-jpeg-content",
        filename="sample.jpg",
        content_type="image/jpeg",
    )

    response = await api_context.client.post(
        "/api/images",
        data=form,
        headers=api_context.auth_headers,
    )

    assert response.status == 503
    assert api_context.database.tasks.rows == {}
    assert list(api_context.storage_path.glob("*.upload")) == []


async def test_get_image_returns_jpeg_bytes(
    api_context: ApiContext,
) -> None:
    """Проверяет получение бинарных данных изображения."""
    image_id = store_image(api_context)
    row = api_context.database.images.rows[image_id]

    response = await api_context.client.get(
        f"/api/images/{image_id}",
        headers=api_context.auth_headers,
    )

    assert response.status == 200
    assert response.headers["Content-Type"] == "image/jpeg"
    assert await response.read() == row["content"]


async def test_resize_creates_worker_task(
    api_context: ApiContext,
) -> None:
    """Проверяет постановку resize-задачи для изображения из БД."""
    image_id = store_image(api_context)

    response = await api_context.client.post(
        "/api/images/resize",
        json={
            "image_id": str(image_id),
            "width": 320,
            "height": 240,
        },
        headers=api_context.auth_headers,
    )

    assert response.status == 202
    task_id = UUID((await response.json())["task_id"])
    task = api_context.database.tasks.rows[task_id]
    assert task["task_type"] == "resize"
    assert task["source_image_id"] == image_id
    assert task["target_width"] == 320
    assert task["target_height"] == 240
    assert api_context.redis.items == [
        ("image_tasks", str(task_id))
    ]


async def test_resize_rejects_unknown_image(
    api_context: ApiContext,
) -> None:
    """Проверяет 404 для неизвестного исходного изображения."""
    response = await api_context.client.post(
        "/api/images/resize",
        json={
            "image_id": str(uuid4()),
            "width": 320,
            "height": 240,
        },
        headers=api_context.auth_headers,
    )

    assert response.status == 404
    assert api_context.redis.items == []


async def test_get_image_metadata(
    api_context: ApiContext,
) -> None:
    """Проверяет получение параметров без бинарного поля."""
    image_id = store_image(api_context)

    response = await api_context.client.get(
        f"/api/images/{image_id}/metadata",
        headers=api_context.auth_headers,
    )

    assert response.status == 200
    payload = await response.json()
    assert payload["id"] == str(image_id)
    assert payload["width"] == 640
    assert payload["height"] == 480
    assert "content" not in payload


async def test_list_images_as_json(
    api_context: ApiContext,
) -> None:
    """Проверяет список параметров в JSON."""
    image_id = store_image(api_context)

    response = await api_context.client.get(
        "/api/images?format=json&limit=10",
        headers=api_context.auth_headers,
    )

    assert response.status == 200
    payload = await response.json()
    assert payload["limit"] == 10
    assert payload["offset"] == 0
    assert payload["items"][0]["id"] == str(image_id)
    assert "content" not in payload["items"][0]


async def test_list_images_as_csv(
    api_context: ApiContext,
) -> None:
    """Проверяет список параметров в CSV."""
    image_id = store_image(api_context)

    response = await api_context.client.get(
        "/api/images?format=csv",
        headers=api_context.auth_headers,
    )

    assert response.status == 200
    assert response.content_type == "text/csv"
    rows = list(csv.DictReader(StringIO(await response.text())))
    assert rows[0]["id"] == str(image_id)
    assert rows[0]["width"] == "640"


async def test_failed_database_compensation_still_removes_file(
    api_context: ApiContext,
) -> None:
    """Проверяет независимое удаление файла при сбое БД."""
    api_context.redis.fail = True
    api_context.database.tasks.fail_delete = True
    form = FormData()
    form.add_field(
        "file",
        b"fake-jpeg-content",
        filename="sample.jpg",
        content_type="image/jpeg",
    )

    response = await api_context.client.post(
        "/api/images",
        data=form,
        headers=api_context.auth_headers,
    )

    assert response.status == 503
    assert len(api_context.database.tasks.rows) == 1
    assert list(api_context.storage_path.glob("*.upload")) == []



async def test_upload_rejects_large_pixel_count(
    api_context: ApiContext,
) -> None:
    """Проверяет предел общего числа пикселей upload-задачи."""
    form = FormData()
    form.add_field(
        "file",
        b"fake-jpeg-content",
        filename="sample.jpg",
        content_type="image/jpeg",
    )
    form.add_field("x", "8000")
    form.add_field("y", "6000")

    response = await api_context.client.post(
        "/api/images",
        data=form,
        headers=api_context.auth_headers,
    )

    assert response.status == 422
    payload = await response.json()
    assert payload["error"]["code"] == "image_pixel_count_too_large"
    assert api_context.redis.items == []


async def test_resize_rejects_large_pixel_count(
    api_context: ApiContext,
) -> None:
    """Проверяет предел общего числа пикселей resize-задачи."""
    image_id = store_image(api_context)

    response = await api_context.client.post(
        "/api/images/resize",
        json={
            "image_id": str(image_id),
            "width": 8000,
            "height": 6000,
        },
        headers=api_context.auth_headers,
    )

    assert response.status == 422
    payload = await response.json()
    assert payload["error"]["code"] == "image_pixel_count_too_large"
    assert api_context.redis.items == []


async def test_list_images_rejects_excessive_limit(
    api_context: ApiContext,
) -> None:
    """Проверяет настроенный предел страницы изображений."""
    response = await api_context.client.get(
        "/api/images?limit=101",
        headers=api_context.auth_headers,
    )

    assert response.status == 422
    payload = await response.json()
    assert payload["error"]["code"] == "list_limit_too_large"
