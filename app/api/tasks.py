from aiohttp import web

from app.api.validation import parse_task_path
from app.dependencies import get_task_service
from app.middlewares.errors import APIError
from app.models.tasks import TaskStatusResponse


routes = web.RouteTableDef()


@routes.get("/api/tasks/{task_id}")
async def get_task_status(request: web.Request) -> web.Response:
    """Возвращает текущий статус фоновой задачи."""
    path = parse_task_path(request)
    service = get_task_service(request)
    task = await service.get_by_id(path.task_id)

    if task is None:
        raise APIError(
            status=404,
            code="task_not_found",
            message="Task not found",
        )

    response = TaskStatusResponse(
        task_id=task.id,
        status=task.status,
        image_id=task.result_image_id,
        error=task.error_message,
    )
    return web.json_response(
        response.model_dump(mode="json", exclude_none=True)
    )
