import asyncio
from pathlib import Path
from uuid import UUID


class FileSystemStorage:
    """Работает с исходными файлами в настроенной директории."""

    def __init__(self, directory: Path) -> None:
        """Сохраняет директорию файлового хранилища."""
        self._directory = directory

    async def prepare(self) -> None:
        """Создаёт директорию хранилища при необходимости."""
        await asyncio.to_thread(
            self._directory.mkdir,
            parents=True,
            exist_ok=True,
        )

    async def save_upload(self, task_id: UUID, content: bytes) -> str:
        """Атомарно сохраняет исходный файл под именем задачи."""
        stored_name = f"{task_id}.upload"
        path = self._path(stored_name)
        operation = asyncio.create_task(
            asyncio.to_thread(self._write_atomic, path, content)
        )

        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            # Дожидаемся файлового потока, чтобы сервис удалил результат.
            await operation
            raise

        return stored_name

    async def read(self, stored_name: str) -> bytes:
        """Читает ранее сохранённый исходный файл."""
        return await asyncio.to_thread(
            self._path(stored_name).read_bytes
        )

    async def delete(self, stored_name: str) -> None:
        """Удаляет исходный файл, если он существует."""
        path = self._path(stored_name)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    def _path(self, stored_name: str) -> Path:
        """Запрещает выход имени файла за директорию хранилища."""
        if not stored_name or Path(stored_name).name != stored_name:
            raise ValueError("Некорректное имя файла хранилища")
        return self._directory / stored_name

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        """Записывает файл через временное имя."""
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary_path.write_bytes(content)
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
