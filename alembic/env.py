"""Настраивает окружение Alembic и запускает миграции в offline/online режимах."""

import os
import time
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.models.base import Base
from app.db import base  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace('+asyncpg', ''))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Запуск миграций в offline режиме.
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Запуск миграций в online режиме.
    retries = int(os.getenv("ALEMBIC_DB_CONNECT_RETRIES", "30"))
    delay_seconds = float(os.getenv("ALEMBIC_DB_CONNECT_RETRY_DELAY", "1"))

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    for attempt in range(1, retries + 1):
        try:
            with connectable.connect() as connection:
                context.configure(connection=connection, target_metadata=target_metadata)
                with context.begin_transaction():
                    context.run_migrations()
            return
        except OperationalError as exc:
            if attempt == retries:
                raise

            error_message = str(getattr(exc, "orig", exc)).lower()
            transient_errors = (
                "the database system is starting up",
                "could not connect to server",
                "connection refused",
            )
            if any(message in error_message for message in transient_errors):
                time.sleep(delay_seconds)
                continue

            raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
