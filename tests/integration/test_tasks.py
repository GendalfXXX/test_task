from aiohttp import FormData

from tests.integration.support import ApiContext


async def test_get_task_status(api_context: ApiContext) -> None:
    """Проверяет получение статуса существующей задачи."""
    form = FormData()
    form.add_field(
        "file",
        b"fake-png-content",
        filename="sample.png",
        content_type="image/png",
    )
    upload_response = await api_context.client.post(
        "/api/images",
        data=form,
        headers=api_context.auth_headers,
    )
    task_id = (await upload_response.json())["task_id"]

    response = await api_context.client.get(
        f"/api/tasks/{task_id}",
        headers=api_context.auth_headers,
    )

    assert response.status == 200
    assert await response.json() == {
        "task_id": task_id,
        "status": "pending",
    }


async def test_get_unknown_task_returns_404(
    api_context: ApiContext,
) -> None:
    """Проверяет 404 для неизвестной задачи."""
    response = await api_context.client.get(
        "/api/tasks/00000000-0000-0000-0000-000000000000",
        headers=api_context.auth_headers,
    )

    assert response.status == 404
