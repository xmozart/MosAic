"""Alembic environment for the control DB. Invoked programmatically by mosaic.storage.db."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from mosaic.storage.models_control import ControlBase

target_metadata = ControlBase.metadata
config = context.config


def run() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run()
