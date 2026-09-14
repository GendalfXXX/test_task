from aiohttp import web

from app.api.images import routes as image_routes
from app.api.logs import routes as log_routes
from app.api.tasks import routes as task_routes


def setup_routes(app: web.Application) -> None:
    """Подключает маршруты API к приложению."""
    app.add_routes(image_routes)
    app.add_routes(task_routes)
    app.add_routes(log_routes)
