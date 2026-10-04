"""Schema upkeep for an existing installation.

``create_all`` makes tables that do not exist yet; it never touches one that
does. So a running instance that is updated to a version with a new column
would keep its old table and fail on the first query. This closes that gap.

Deliberately not Alembic: every change this application has needed is an added
column with a default, SQLite can do that in place, and a migration tool that
has to be kept in step with its own version table is more machinery than the
problem deserves. Anything beyond an added column -- a renamed or dropped one,
a changed type -- is not handled here and would need a real migration.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("gcg.migrations")

# table -> column -> SQL type and default, exactly as it must be added
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "images": {
        "note": "VARCHAR(200) DEFAULT ''",
        "settings": "JSON",
        "processed": "BOOLEAN DEFAULT 0",
    },
}


def apply(engine: Engine) -> list[str]:
    """Add any column the running code expects and the database lacks."""
    applied: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table, columns in ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all will build it complete
            present = {c["name"] for c in inspector.get_columns(table)}
            for column, definition in columns.items():
                if column in present:
                    continue
                connection.execute(
                    text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'))
                applied.append(f"{table}.{column}")
                log.info("Spalte ergänzt: %s.%s", table, column)
    return applied
