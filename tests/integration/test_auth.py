from io import BytesIO

from tests.integration.support import ApiContext


async def test_rejects_request_without_token(
    api_context: ApiContext,
) -> None:
    """Проверяет обязательность bearer-токена."""
    response = await api_context.client.get("/api/images")

    assert response.status == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_rejects_invalid_token(
    api_context: ApiContext,
) -> None:
    """Проверяет отказ для неверного bearer-токена."""
    response = await api_context.client.get(
        "/api/images",
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status == 401


async def test_accepts_valid_token(
    api_context: ApiContext,
) -> None:
    """Проверяет доступ с корректным bearer-токеном."""
    response = await api_context.client.get(
        "/api/images",
        headers=api_context.auth_headers,
    )

    assert response.status == 200


async def test_rejects_unauthorized_body_before_parsing(
    api_context: ApiContext,
) -> None:
    """Проверяет авторизацию до чтения большого JSON."""
    body = b'{"unused":"' + b"x" * (1024 * 1024) + b'"}'

    response = await api_context.client.post(
        "/api/images/resize",
        data=BytesIO(body),
        headers={"Content-Type": "application/json"},
    )

    assert response.status == 401


async def test_large_authorized_json_has_structured_error(
    api_context: ApiContext,
) -> None:
    """Проверяет обработку превышения размера JSON."""
    body = b'{"unused":"' + b"x" * (1024 * 1024) + b'"}'
    headers = {
        **api_context.auth_headers,
        "Content-Type": "application/json",
    }

    response = await api_context.client.post(
        "/api/images/resize",
        data=BytesIO(body),
        headers=headers,
    )

    assert response.status == 413
    payload = await response.json()
    assert payload["error"]["code"] == "http_413"
    assert response.headers["X-Request-ID"]

