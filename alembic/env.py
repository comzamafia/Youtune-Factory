from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# ── App integration ────────────────────────────────────────────────────────────
# Import settings and models so Alembic can read DATABASE_URL from .env
# and use our SQLAlchemy metadata for autogenerate.
import sys
import os

# Add project root to path so `app` package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import settings
from app.core.models import Base  # noqa: E402 — imports all mapped models

# ──────────────────────────────────────────────────────────────────────────────

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Point Alembic at our models for --autogenerate support
target_metadata = Base.metadata

# Override the sqlalchemy.url from alembic.ini with the value from .env
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a live connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Compare server defaults so nullable/default changes are detected
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (applies changes to the live database)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

