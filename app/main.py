from aiohttp import web

from app.application import create_app
from app.config import load_settings


def main() -> None:
    """Запускает HTTP API с настройками проекта."""
    settings = load_settings()

    web.run_app(
        create_app(settings),
        host=settings.api.host,
        port=settings.api.port,
    )


if __name__ == "__main__":
    main()
