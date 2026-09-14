import json

from loguru import logger

from tests.integration.support import ApiContext


async def test_reads_latest_jsonl_records(
    api_context: ApiContext,
) -> None:
    """Проверяет чтение ограниченного хвоста JSONL-лога."""
    await logger.complete()
    records = [
        {"time": "first", "message": "one"},
        {"time": "second", "message": "two"},
        {"time": "third", "message": "three"},
    ]
    api_context.log_path.write_text(
        "".join(
            json.dumps(record) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )

    response = await api_context.client.get(
        "/api/logs?limit=2",
        headers=api_context.auth_headers,
    )

    assert response.status == 200
    payload = await response.json()
    assert payload["limit"] == 2
    assert payload["items"] == records[-2:]


async def test_rejects_excessive_log_limit(
    api_context: ApiContext,
) -> None:
    """Проверяет верхнюю границу чтения логов."""
    response = await api_context.client.get(
        "/api/logs?limit=1001",
        headers=api_context.auth_headers,
    )

    assert response.status == 422

