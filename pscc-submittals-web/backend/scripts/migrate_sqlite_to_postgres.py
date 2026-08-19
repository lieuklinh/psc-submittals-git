"""
One-time migration: copies every row from the Streamlit app's SQLite
database (pscc-submittals-agent/data/app.db) into the new Postgres
database used by this backend. Safe to re-run — every insert uses
ON CONFLICT DO NOTHING, so already-migrated rows are skipped rather than
duplicated or overwritten.

Also copies the on-disk files a project references (source PDF, output
ZIP, extracted sections/log Excel files) into this backend's data/
folders and rewrites the corresponding path columns, so downloads and
"Edit details / regenerate" keep working from the new backend.

Usage (from backend/):
    venv/Scripts/python.exe scripts/migrate_sqlite_to_postgres.py [--sqlite-path PATH]

Run this AFTER the FastAPI app has started at least once (so init_db()
has created the Postgres schema), or call db.init_db() is invoked here
too, just to be safe.
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app import config, db  # noqa: E402

DEFAULT_SQLITE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "pscc-submittals-agent" / "data" / "app.db"
)

# Table order matters — parents before children, matching the foreign key
# dependencies declared in db.py's init_db().
TABLE_ORDER = [
    "users",
    "projects",
    "sections",
    "assignments",
    "notifications",
    "section_flags",
    "project_members",
    "organizations",
    "specification_sections",
    "submittal_items",
    "activity_log",
    "attachments",
    "comments",
]

# Primary/conflict key(s) per table — most use a single "id" column, but a
# few use composite or differently-named keys.
CONFLICT_COLUMNS = {
    "assignments": ["section_id"],
    "project_members": ["project_id", "user_email"],
}

# project columns that hold absolute file paths worth carrying over.
PROJECT_FILE_COLUMNS = {
    "source_pdf_path": config.UPLOADS_DIR,
    "output_zip_path": config.OUTPUTS_DIR,
    "sections_xlsx_path": config.OUTPUTS_DIR,
    "log_xlsx_path": config.OUTPUTS_DIR,
}


def _copy_project_files(sqlite_conn):
    """Copies each project's referenced files into this backend's data/
    dirs and returns {project_id: {column: new_path}} overrides."""
    overrides = {}
    rows = sqlite_conn.execute(
        f"SELECT id, {', '.join(PROJECT_FILE_COLUMNS)} FROM projects"
    ).fetchall()
    for row in rows:
        project_id = row["id"]
        col_overrides = {}
        for col, dest_dir in PROJECT_FILE_COLUMNS.items():
            old_path = row[col]
            if not old_path:
                continue
            old_path = Path(old_path)
            if not old_path.exists():
                print(f"  ! {col} for project {project_id} missing on disk, skipping: {old_path}")
                continue
            new_path = dest_dir / old_path.name
            if not new_path.exists():
                shutil.copy2(old_path, new_path)
            col_overrides[col] = str(new_path)
        if col_overrides:
            overrides[project_id] = col_overrides
    return overrides


def _attachment_dest(sqlite_conn):
    """Copies attachment files into this backend's attachments/<item_id>/
    dir and returns {attachment_id: new_path}."""
    overrides = {}
    rows = sqlite_conn.execute("SELECT id, submittal_item_id, file_path FROM attachments").fetchall()
    for row in rows:
        old_path = Path(row["file_path"]) if row["file_path"] else None
        if not old_path or not old_path.exists():
            continue
        dest_dir = config.ATTACHMENTS_DIR / row["submittal_item_id"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        new_path = dest_dir / old_path.name
        if not new_path.exists():
            shutil.copy2(old_path, new_path)
        overrides[row["id"]] = str(new_path)
    return overrides


def migrate(sqlite_path: Path):
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite file not found: {sqlite_path}")

    print(f"Source: {sqlite_path}")
    print(f"Target: {config.DATABASE_URL}")

    db.init_db()

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row

    print("Copying referenced project files (PDF/zip/xlsx)...")
    project_overrides = _copy_project_files(sqlite_conn)
    print(f"  {len(project_overrides)} project(s) had files copied.")

    print("Copying attachment files...")
    attachment_overrides = _attachment_dest(sqlite_conn)
    print(f"  {len(attachment_overrides)} attachment(s) had files copied.")

    pg_conn = db._connect()
    total_inserted = 0

    for table in TABLE_ORDER:
        rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"{table}: 0 rows, skipping")
            continue

        columns = rows[0].keys()
        inserted = 0
        for row in rows:
            values = dict(row)
            if table == "projects" and values["id"] in project_overrides:
                values.update(project_overrides[values["id"]])
            if table == "attachments" and values["id"] in attachment_overrides:
                values["file_path"] = attachment_overrides[values["id"]]

            col_list = ", ".join(columns)
            placeholders = ", ".join(f":{c}" for c in columns)
            conflict_cols = ", ".join(CONFLICT_COLUMNS.get(table, ["id"]))
            result = pg_conn.execute(text(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_cols}) DO NOTHING"
            ), values)
            inserted += result.rowcount

        pg_conn.commit()
        total_inserted += inserted
        print(f"{table}: {inserted}/{len(rows)} row(s) inserted (rest already present)")

    pg_conn.close()
    sqlite_conn.close()
    print(f"\nDone. {total_inserted} new row(s) migrated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", type=Path, default=DEFAULT_SQLITE_PATH,
                         help="Path to the Streamlit app's SQLite file (default: ../pscc-submittals-agent/data/app.db)")
    args = parser.parse_args()
    migrate(args.sqlite_path)
