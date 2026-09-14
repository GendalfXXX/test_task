import os
from configparser import ConfigParser
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, model_validator


class ApiSettings(BaseModel):
    """Хранит настройки HTTP API."""

    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    max_upload_size_bytes: int = Field(default=10_485_760, gt=0)
    max_image_dimension: int = Field(default=10_000, gt=0)
    max_image_pixels: int = Field(default=40_000_000, gt=0)
    image_list_limit: int = Field(default=100, gt=0, le=1000)


class DatabaseSettings(BaseModel):
    """Хранит настройки подключения к PostgreSQL."""

    dsn: SecretStr
    min_pool_size: int = Field(default=1, ge=1)
    max_pool_size: int = Field(default=10, ge=1)
    command_timeout: float = Field(default=30.0, gt=0)
    migrations_directory: Path = Path("app/db/migrations")


class RedisSettings(BaseModel):
    """Хранит настройки очереди Redis."""

    dsn: SecretStr
    queue_name: str = Field(default="image_tasks", min_length=1)


class AuthSettings(BaseModel):
    """Хранит токен доступа к API."""

    bearer_token: SecretStr


class StorageSettings(BaseModel):
    """Хранит настройки файлового хранилища."""

    image_directory: Path


class LoggingSettings(BaseModel):
    """Хранит настройки JSONL-логирования и чтения логов."""

    enabled: bool = True
    stdout: bool = True
    file: bool = True
    file_path: Path = Path("logs/application.jsonl")
    level: str = "INFO"
    rotation: str = "10 MB"
    retention: str = "14 days"
    read_limit: int = Field(default=100, gt=0, le=10_000)
    max_read_limit: int = Field(default=1000, gt=0, le=10_000)

    @model_validator(mode="after")
    def validate_read_limits(self) -> "LoggingSettings":
        """Проверяет согласованность лимитов чтения."""
        if self.read_limit > self.max_read_limit:
            raise ValueError(
                "logging.read_limit cannot exceed max_read_limit"
            )
        return self


class Settings(BaseModel):
    """Объединяет настройки приложения."""

    api: ApiSettings
    database: DatabaseSettings
    redis: RedisSettings
    auth: AuthSettings
    storage: StorageSettings
    logging: LoggingSettings


def _required_environment(name: str) -> str:
    """Возвращает обязательную переменную окружения."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def load_settings(
    config_path: Path = Path("config.cfg"),
    env_path: Path = Path(".env"),
) -> Settings:
    """Загружает полную конфигурацию приложения."""
    load_dotenv(dotenv_path=env_path)

    parser = ConfigParser()
    if not parser.read(config_path, encoding="utf-8"):
        raise RuntimeError(f"Configuration file not found: {config_path}")

    min_pool_size = parser.getint("database", "min_pool_size")
    max_pool_size = parser.getint("database", "max_pool_size")
    if min_pool_size > max_pool_size:
        raise RuntimeError(
            "database.min_pool_size cannot exceed database.max_pool_size"
        )

    return Settings(
        api=ApiSettings(
            host=parser.get("api", "host"),
            port=parser.getint("api", "port"),
            max_upload_size_bytes=parser.getint(
                "api", "max_upload_size_bytes"
            ),
            max_image_dimension=parser.getint(
                "api", "max_image_dimension"
            ),
            max_image_pixels=parser.getint(
                "api", "max_image_pixels"
            ),
            image_list_limit=parser.getint(
                "api", "image_list_limit"
            ),
        ),
        database=DatabaseSettings(
            dsn=_required_environment("POSTGRES_DSN"),
            min_pool_size=min_pool_size,
            max_pool_size=max_pool_size,
            command_timeout=parser.getfloat("database", "command_timeout"),
            migrations_directory=Path(
                parser.get("database", "migrations_directory")
            ),
        ),
        redis=RedisSettings(
            dsn=_required_environment("REDIS_DSN"),
            queue_name=parser.get("redis", "queue_name"),
        ),
        auth=AuthSettings(
            bearer_token=_required_environment("BEARER_TOKEN"),
        ),
        storage=StorageSettings(
            image_directory=Path(
                parser.get("storage", "image_directory")
            ),
        ),
        logging=LoggingSettings(
            enabled=parser.getboolean("logging", "enabled"),
            stdout=parser.getboolean("logging", "stdout"),
            file=parser.getboolean("logging", "file"),
            file_path=Path(parser.get("logging", "file_path")),
            level=parser.get("logging", "level"),
            rotation=parser.get("logging", "rotation"),
            retention=parser.get("logging", "retention"),
            read_limit=parser.getint("logging", "read_limit"),
            max_read_limit=parser.getint(
                "logging", "max_read_limit"
            ),
        ),
    )


def load_migration_settings(
    config_path: Path = Path("config.cfg"),
    env_path: Path = Path(".env"),
) -> Tuple[DatabaseSettings, LoggingSettings]:
    """Загружает настройки PostgreSQL и миграций."""
    load_dotenv(dotenv_path=env_path)

    parser = ConfigParser()
    if not parser.read(config_path, encoding="utf-8"):
        raise RuntimeError(f"Configuration file not found: {config_path}")

    min_pool_size = parser.getint("database", "min_pool_size")
    max_pool_size = parser.getint("database", "max_pool_size")
    if min_pool_size > max_pool_size:
        raise RuntimeError(
            "database.min_pool_size cannot exceed database.max_pool_size"
        )

    database = DatabaseSettings(
        dsn=_required_environment("POSTGRES_DSN"),
        min_pool_size=min_pool_size,
        max_pool_size=max_pool_size,
        command_timeout=parser.getfloat("database", "command_timeout"),
        migrations_directory=Path(
            parser.get("database", "migrations_directory")
        ),
    )
    logging = LoggingSettings(
        enabled=parser.getboolean("logging", "enabled"),
        stdout=parser.getboolean("logging", "stdout"),
        file=parser.getboolean("logging", "file"),
        file_path=Path(parser.get("logging", "file_path")),
        level=parser.get("logging", "level"),
        rotation=parser.get("logging", "rotation"),
        retention=parser.get("logging", "retention"),
        read_limit=parser.getint("logging", "read_limit"),
        max_read_limit=parser.getint("logging", "max_read_limit"),
    )

    return database, logging
