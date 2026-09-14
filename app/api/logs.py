from aiohttp import web

from app.api.validation import parse_log_limit
from app.dependencies import get_log_service
from app.models.logs import LogListResponse


routes = web.RouteTableDef()


@routes.get("/api/logs")
async def get_logs(request: web.Request) -> web.Response:
    """Возвращает последние записи JSONL-лога."""
    limit = parse_log_limit(request)

    service = get_log_service(request)
    items = await service.get_latest(limit)
    response = LogListResponse(items=items, limit=limit)
    return web.json_response(response.model_dump(mode="json"))
