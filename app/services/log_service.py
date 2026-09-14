import asyncio
import json
from collections import deque
from pathlib import Path
from typing import Any, Dict, List

from app.config import LoggingSettings


class LogService:
    """Читает последние записи настроенного JSONL-файла."""

    def __init__(self, settings: LoggingSettings) -> None:
        """Сохраняет настройки логирования."""
        self._settings = settings

    async def get_latest(self, limit: int) -> List[Dict[str, Any]]:
        """Возвращает последние записи, не блокируя event loop."""
        return await asyncio.to_thread(self._read_latest, limit)

    def _read_latest(self, limit: int) -> List[Dict[str, Any]]:
        """Синхронно читает ограниченный хвост файла."""
        path = self._settings.file_path
        if not self._is_readable(path):
            return []

        lines = deque(maxlen=limit)
        try:
            with path.open("r", encoding="utf-8") as log_file:
                for line in log_file:
                    if line.strip():
                        lines.append(line)
        except FileNotFoundError:
            # Файл мог ротироваться между проверкой и открытием.
            return []

        result = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                item = {
                    "message": "invalid_log_line",
                    "raw": line.rstrip(),
                }
            result.append(item)

        return result

    def _is_readable(self, path: Path) -> bool:
        """Проверяет, включено ли файловое логирование."""
        return (
            self._settings.enabled
            and self._settings.file
            and path.is_file()
        )

