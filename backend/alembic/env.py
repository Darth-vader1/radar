import os
import sys
from logging.config import fileConfig

from alembic import context
import sqlalchemy as sa
from sqlalchemy import engine_from_config, pool

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.models import Base

# this is the Alembic Config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url():
    return settings.DATABASE_SYNC_URL


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section)
    if configuration is None:
        configuration = {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            # Enable PostgreSQL extensions
            connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS \"pgcrypto\";"))
            connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS \"pg_trgm\";"))
            connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS \"unaccent\";"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import sqlalchemy as sa
    run_migrations_online()
