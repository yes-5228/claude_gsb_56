"""Lightweight idempotent schema bootstrap.

The project relies on ``db.create_all()`` (no migration tool). New tables are
created automatically, but columns added to existing tables are not. This
helper issues additive ``ALTER TABLE`` statements only when a column is
missing, so upgraded deployments keep their data.
"""
from sqlalchemy import inspect, text

from .extensions import db


def _has_column(inspector, table, column):
    return column in {item["name"] for item in inspector.get_columns(table)}


def ensure_schema():
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    if "measurements" in existing_tables and not _has_column(
        inspector, "measurements", "version"
    ):
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE measurements ADD COLUMN version INTEGER"))
            conn.execute(text("UPDATE measurements SET version = 1 WHERE version IS NULL"))

    if "exceedances" in existing_tables:
        statements = []
        if not _has_column(inspector, "exceedances", "source_version_id"):
            statements.append("ALTER TABLE exceedances ADD COLUMN source_version_id INTEGER")
        if not _has_column(inspector, "exceedances", "regenerated"):
            statements.append("ALTER TABLE exceedances ADD COLUMN regenerated BOOLEAN")
        if statements:
            with db.engine.begin() as conn:
                for statement in statements:
                    conn.execute(text(statement))
                conn.execute(
                    text("UPDATE exceedances SET regenerated = 0 WHERE regenerated IS NULL")
                )

    # create_all() then picks up the new measurement_versions table and FKs.
    db.create_all()
