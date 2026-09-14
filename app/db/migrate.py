import argparse
import asyncio
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Dict, List, Sequence

import asyncpg
from loguru import logger

from app.config import DatabaseSettings, load_migration_settings
from app.logging_config import configure_logging


MIGRATION_FILE_PATTERN = re.compile(
    r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$"
)
MIGRATION_LOCK_ID = 724_190_831
BOOTSTRAP_SCHEMA_PATH = Path(__file__).parent / "sql" / "schema.sql"


class MigrationError(RuntimeError):
    """Описывает ошибку истории миграций."""


@dataclass(frozen=True)
class Migration:
    """Описывает SQL-файл миграции."""

    version: str
    name: str
    sql: str
    checksum: str
    path: Path


@dataclass(frozen=True)
class MigrationStatus:
    """Описывает состояние одной миграции."""

    migration: Migration
    applied: bool


def _read_sql(path: Path) -> str:
    """Читает и нормализует SQL-файл."""
    sql = path.read_text(encoding="utf-8-sig")
    sql = sql.replace("\r\n", "\n").replace("\r", "\n")

    if not sql.strip():
        raise MigrationError(f"Migration is empty: {path}")

    return sql


def discover_migrations(directory: Path) -> List[Migration]:
    """Находит и проверяет миграции в директории."""
    if not directory.is_dir():
        raise MigrationError(f"Migration directory not found: {directory}")

    migrations: List[Migration] = []
    versions = set()

    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_FILE_PATTERN.fullmatch(path.name)
        if match is None:
            raise MigrationError(
                "Invalid migration filename "
                f"{path.name!r}; expected 0001_short_name.sql"
            )

        version = match.group("version")
        if version in versions:
            raise MigrationError(f"Duplicate migration version: {version}")

        sql = _read_sql(path)
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                sql=sql,
                checksum=sha256(sql.encode("utf-8")).hexdigest(),
                path=path,
            )
        )
        versions.add(version)

    if not migrations:
        raise MigrationError(f"No migration files found in: {directory}")

    return migrations


async def _load_applied(
    connection: asyncpg.Connection,
) -> Dict[str, str]:
    """Загружает версии применённых миграций."""
    rows = await connection.fetch(
        """
        SELECT version, checksum
        FROM schema_migrations
        ORDER BY version
        """
    )
    return {row["version"]: row["checksum"] for row in rows}


def _validate_history(
    migrations: Sequence[Migration],
    applied: Dict[str, str],
) -> None:
    """Сверяет файлы с историей PostgreSQL."""
    known = {migration.version: migration for migration in migrations}

    for version, stored_checksum in applied.items():
        migration = known.get(version)
        if migration is None:
            raise MigrationError(
                f"Applied migration {version} is missing from the project"
            )
        if migration.checksum != stored_checksum:
            raise MigrationError(
                f"Applied migration {version} was modified; "
                "create a new migration instead"
            )

    if applied:
        latest_applied = max(applied)
        inserted_versions = [
            migration.version
            for migration in migrations
            if migration.version not in applied
            and migration.version < latest_applied
        ]
        if inserted_versions:
            raise MigrationError(
                "New migrations cannot be inserted before the latest applied "
                f"version: {', '.join(inserted_versions)}"
            )


async def _prepare(
    connection: asyncpg.Connection,
    migrations: Sequence[Migration],
) -> Dict[str, str]:
    """Подготавливает таблицу истории миграций."""
    bootstrap_sql = _read_sql(BOOTSTRAP_SCHEMA_PATH)
    await connection.execute(bootstrap_sql)
    applied = await _load_applied(connection)
    _validate_history(migrations, applied)
    return applied


async def apply_migrations(settings: DatabaseSettings) -> int:
    """Применяет все новые миграции по порядку."""
    migrations = discover_migrations(settings.migrations_directory)
    connection = await asyncpg.connect(
        dsn=settings.dsn.get_secret_value(),
        command_timeout=settings.command_timeout,
    )

    applied_count = 0
    try:
        await connection.fetchval(
            "SELECT pg_advisory_lock($1::bigint)",
            MIGRATION_LOCK_ID,
        )
        applied = await _prepare(connection, migrations)

        for migration in migrations:
            if migration.version in applied:
                continue

            async with connection.transaction():
                await connection.execute(migration.sql)
                await connection.execute(
                    """
                    INSERT INTO schema_migrations (version, checksum)
                    VALUES ($1, $2)
                    """,
                    migration.version,
                    migration.checksum,
                )

            applied_count += 1
            logger.bind(
                migration_version=migration.version,
                migration_name=migration.name,
            ).info("migration_applied")
    finally:
        if not connection.is_closed():
            try:
                await connection.fetchval(
                    "SELECT pg_advisory_unlock($1::bigint)",
                    MIGRATION_LOCK_ID,
                )
            finally:
                await connection.close()

    return applied_count


async def get_migration_status(
    settings: DatabaseSettings,
) -> List[MigrationStatus]:
    """Возвращает состояние файлов миграций."""
    migrations = discover_migrations(settings.migrations_directory)
    connection = await asyncpg.connect(
        dsn=settings.dsn.get_secret_value(),
        command_timeout=settings.command_timeout,
    )

    try:
        await connection.fetchval(
            "SELECT pg_advisory_lock($1::bigint)",
            MIGRATION_LOCK_ID,
        )
        migration_table_exists = await connection.fetchval(
            "SELECT TO_REGCLASS('schema_migrations') IS NOT NULL"
        )
        applied = (
            await _load_applied(connection)
            if migration_table_exists
            else {}
        )
        _validate_history(migrations, applied)

        return [
            MigrationStatus(
                migration=migration,
                applied=migration.version in applied,
            )
            for migration in migrations
        ]
    finally:
        if not connection.is_closed():
            try:
                await connection.fetchval(
                    "SELECT pg_advisory_unlock($1::bigint)",
                    MIGRATION_LOCK_ID,
                )
            finally:
                await connection.close()


def _parse_arguments() -> argparse.Namespace:
    """Читает команду мигратора из CLI."""
    parser = argparse.ArgumentParser(
        description="Apply or inspect PostgreSQL migrations"
    )
    parser.add_argument(
        "command",
        choices=("up", "status"),
        nargs="?",
        default="up",
    )
    return parser.parse_args()


async def _run(command: str, settings: DatabaseSettings) -> None:
    """Выполняет выбранную команду мигратора."""
    if command == "status":
        statuses = await get_migration_status(settings)
        for status in statuses:
            logger.bind(
                migration_version=status.migration.version,
                migration_name=status.migration.name,
                migration_state=(
                    "applied" if status.applied else "pending"
                ),
            ).info("migration_status")
        return

    applied_count = await apply_migrations(settings)
    logger.bind(applied_count=applied_count).info("migrations_finished")


def main() -> None:
    """Запускает CLI чистых asyncpg-миграций."""
    arguments = _parse_arguments()
    database_settings, logging_settings = load_migration_settings()
    configure_logging(logging_settings)

    try:
        asyncio.run(_run(arguments.command, database_settings))
    except Exception:
        logger.exception("migration_command_failed")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
