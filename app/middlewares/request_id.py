from typing import Awaitable, Callable
from uuid import uuid4

from aiohttp import web


REQUEST_ID_KEY = web.RequestKey("request_id", str)

Handler = Callable[
    [web.Request],
    Awaitable[web.StreamResponse],
]


@web.middleware
async def request_id_middleware(
    request: web.Request,
    handler: Handler,
) -> web.StreamResponse:
    """Назначает запросу уникальный идентификатор."""
    request_id = str(uuid4())
    request[REQUEST_ID_KEY] = request_id

    response = await handler(request)
    response.headers["X-Request-ID"] = request_id

    return response
