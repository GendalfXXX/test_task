from pathlib import Path

import pytest

from app.db.migrate import (
    MigrationError,
    _validate_history,
    discover_migrations,
)


def test_discovers_migrations_in_version_order(
    tmp_path: Path,
) -> None:
    """Проверяет сортировку найденных миграций."""
    (tmp_path / "0002_second.sql").write_text(
        "SELECT 2;", encoding="utf-8"
    )
    (tmp_path / "0001_first.sql").write_text(
        "SELECT 1;", encoding="utf-8"
    )

    migrations = discover_migrations(tmp_path)

    assert [
        migration.version
        for migration in migrations
    ] == ["0001", "0002"]
    assert all(
        len(migration.checksum) == 64
        for migration in migrations
    )


def test_rejects_invalid_filename(tmp_path: Path) -> None:
    """Проверяет отказ для имени без версии."""
    (tmp_path / "create_table.sql").write_text(
        "SELECT 1;", encoding="utf-8"
    )

    with pytest.raises(MigrationError):
        discover_migrations(tmp_path)


def test_rejects_duplicate_version(tmp_path: Path) -> None:
    """Проверяет отказ для повторяющейся версии."""
    (tmp_path / "0001_first.sql").write_text(
        "SELECT 1;", encoding="utf-8"
    )
    (tmp_path / "0001_second.sql").write_text(
        "SELECT 2;", encoding="utf-8"
    )

    with pytest.raises(MigrationError):
        discover_migrations(tmp_path)


def test_rejects_modified_applied_migration() -> None:
    """Проверяет неизменность применённой миграции."""
    migrations = discover_migrations(Path("app/db/migrations"))

    with pytest.raises(MigrationError):
        _validate_history(
            migrations,
            {migrations[0].version: "not-the-real-checksum"},
        )


def test_rejects_migration_inserted_before_latest_version() -> None:
    """Проверяет линейную историю миграций."""
    migrations = discover_migrations(Path("app/db/migrations"))
    latest = migrations[-1]

    with pytest.raises(MigrationError):
        _validate_history(
            migrations,
            {latest.version: latest.checksum},
        )
