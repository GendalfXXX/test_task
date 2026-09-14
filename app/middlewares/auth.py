import hmac

from aiohttp import web

from app.dependencies import SETTINGS_KEY
from app.middlewares.errors import error_response


AUTHENTICATED_KEY = web.RequestKey("authenticated", bool)


@web.middleware
async def auth_middleware(
    request: web.Request,
    handler,
) -> web.StreamResponse:
    """Проверяет bearer-токен запроса."""
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")

    expected_token = (
        request.app[SETTINGS_KEY]
        .auth.bearer_token
        .get_secret_value()
    )

    is_authenticated = (
        separator == " "
        and scheme.lower() == "bearer"
        and bool(token.strip())
        and hmac.compare_digest(
            token.strip(),
            expected_token,
        )
    )

    if not is_authenticated:
        return error_response(
            request=request,
            status=401,
            code="unauthorized",
            message="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    request[AUTHENTICATED_KEY] = True
    return await handler(request)
