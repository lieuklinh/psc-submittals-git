"""
db.py — PostgreSQL persistence for the Submittal Extractor web backend.

This is the same schema and function surface as the Streamlit app's db.py
(pscc-submittals-agent/db.py), adapted to run standalone behind a FastAPI
service instead of being called in-process from Streamlit. Every function
here is a direct port — same signatures, same behavior — so the migration
script and the router layer can rely on identical semantics to the app
your team already knows.

CONNECTION CONFIG: reads DATABASE_URL from the environment (see config.py /
.env.example). Local dev default assumes PostgreSQL 17 installed via
`winget install PostgreSQL.PostgreSQL.17` with the `pscc_submittals`
database created (see README "Local development" section).
"""

import hashlib
import re
import uuid
import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from . import config

# pool_pre_ping avoids "server closed the connection unexpectedly" errors
# after Postgres or a local dev machine has been idle/asleep.
engine: Engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, future=True)


def _connect():
    return engine.connect()


def init_db():
    """Safe to call on every app startup — CREATE TABLE IF NOT EXISTS and
    ADD COLUMN IF NOT EXISTS only, both natively idempotent in Postgres."""
    conn = _connect()

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL
        )
        """
    ))

    # Operations Team Directory (2026-08 collaborative-workspace spec,
    # section 4) — a company-wide, searchable roster so inviting someone
    # to a project is "search Charles" rather than typing an email. Starts
    # empty per-field and fills in as people are invited/updated; there's
    # no company HR source to sync from yet.
    for col in ("job_title", "department", "office", "phone"):
        conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} TEXT"))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            file_hash TEXT UNIQUE NOT NULL,
            original_filename TEXT,
            uploaded_by TEXT NOT NULL,
            workflow_status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS sections (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            section_code TEXT NOT NULL,
            description TEXT,
            order_index INTEGER NOT NULL
        )
        """
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS assignments (
            section_id TEXT PRIMARY KEY REFERENCES sections(id),
            assigned_to TEXT,
            assigned_by TEXT,
            assigned_at TEXT
        )
        """
    ))

    for col, col_type in {
        "submittal_type": "TEXT",
        "sub_vendor": "TEXT",
        "due_date": "TEXT",
        "received_date": "TEXT",
        "float_days": "TEXT",
    }.items():
        conn.execute(text(f"ALTER TABLE sections ADD COLUMN IF NOT EXISTS {col} {col_type}"))

    conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'member'"
    ))

    for col in ("output_zip_path", "qna_doc_id", "source_pdf_path", "sections_xlsx_path",
                "log_xlsx_path", "project_info_json", "delete_requested_by",
                "delete_requested_at", "legacy_migrated_at"):
        conn.execute(text(f"ALTER TABLE projects ADD COLUMN IF NOT EXISTS {col} TEXT"))

    conn.execute(text(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS pinned INTEGER NOT NULL DEFAULT 0"
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            user_email TEXT NOT NULL,
            project_id TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0
        )
        """
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS section_flags (
            id TEXT PRIMARY KEY,
            section_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            original_code TEXT,
            embedded_code TEXT,
            description TEXT,
            llm_explanation TEXT,
            suggested_code TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            resolved_value TEXT,
            resolved_by TEXT,
            resolved_at TEXT
        )
        """
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS project_members (
            project_id TEXT NOT NULL REFERENCES projects(id),
            user_email TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'assignee',
            status TEXT NOT NULL DEFAULT 'active',
            invited_by TEXT,
            invited_at TEXT NOT NULL,
            PRIMARY KEY (project_id, user_email)
        )
        """
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            organization_name TEXT NOT NULL,
            organization_type TEXT NOT NULL DEFAULT 'subcontractor',
            primary_contact_name TEXT,
            email TEXT,
            phone TEXT,
            trade TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS specification_sections (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            section_number TEXT NOT NULL,
            section_name TEXT,
            section_text_reference TEXT,
            section_summary TEXT,
            summary_generated_at TEXT,
            summary_model TEXT,
            summary_version TEXT,
            order_index INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    ))

    # Section-level internal assignment + Not Required, per the 2026-08
    # collaborative-workspace spec — assignment previously lived only on
    # individual submittal_items; a section's assignee applies to every
    # submittal under it unless a specific item overrides it.
    conn.execute(text(
        "ALTER TABLE specification_sections ADD COLUMN IF NOT EXISTS assigned_user_email TEXT"
    ))
    conn.execute(text(
        "ALTER TABLE specification_sections ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'"
    ))
    conn.execute(text(
        "ALTER TABLE specification_sections ADD COLUMN IF NOT EXISTS not_required_reason TEXT"
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS submittal_items (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            specification_section_id TEXT NOT NULL REFERENCES specification_sections(id),
            suffix TEXT NOT NULL,
            display_number TEXT NOT NULL,
            title TEXT NOT NULL,
            submittal_type TEXT,
            submittal_type_other TEXT,
            organization_id TEXT REFERENCES organizations(id),
            responsible_user_email TEXT,
            status TEXT NOT NULL DEFAULT 'unassigned',
            status_reason TEXT,
            due_date TEXT,
            notes TEXT,
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    ))

    # revision_letter: the resubmittal revision suffix (A, B, C...) shown
    # in "Version" — separate from `suffix` (the fixed 3-digit sequence
    # number), so it can be bumped independently on resubmittal.
    # order_index: manual drag/up-down ordering within a section, distinct
    # from the numbering suffix — nullable so existing rows can be
    # backfilled once below without clobbering it on every startup.
    conn.execute(text(
        "ALTER TABLE submittal_items ADD COLUMN IF NOT EXISTS revision_letter TEXT NOT NULL DEFAULT 'A'"
    ))
    conn.execute(text(
        "ALTER TABLE submittal_items ADD COLUMN IF NOT EXISTS order_index INTEGER"
    ))
    conn.execute(text(
        """
        UPDATE submittal_items si
        SET order_index = sub.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY specification_section_id ORDER BY suffix) - 1 AS rn
            FROM submittal_items
        ) sub
        WHERE si.id = sub.id AND si.order_index IS NULL
        """
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS activity_log (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            submittal_item_id TEXT,
            actor_email TEXT NOT NULL,
            action_type TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            created_at TEXT NOT NULL
        )
        """
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            submittal_item_id TEXT NOT NULL REFERENCES submittal_items(id),
            project_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            uploaded_by TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        )
        """
    ))

    # Approved folder classification (2026-08 spec, section 10): every
    # file belongs to exactly one of the four standard folders. description
    # is required at the API layer (not DB-level NOT NULL, so existing
    # pre-this-feature attachments don't need backfilling). vendor_version
    # (V1/V2/V3) and formal_revision (A/B/C) are filled in once the vendor
    # and Engineer workflows (Phase 3/4) exist.
    conn.execute(text(
        "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS folder TEXT NOT NULL DEFAULT 'from_vendor'"
    ))
    conn.execute(text("ALTER TABLE attachments ADD COLUMN IF NOT EXISTS description TEXT"))
    conn.execute(text("ALTER TABLE attachments ADD COLUMN IF NOT EXISTS vendor_version TEXT"))
    conn.execute(text("ALTER TABLE attachments ADD COLUMN IF NOT EXISTS formal_revision TEXT"))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS comments (
            id TEXT PRIMARY KEY,
            submittal_item_id TEXT NOT NULL REFERENCES submittal_items(id),
            project_id TEXT NOT NULL,
            author_email TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    ))

    conn.commit()
    conn.close()


SUBMITTAL_TYPES = [
    ("product_data", "Product Data"),
    ("shop_drawings", "Shop Drawings"),
    ("samples", "Samples"),
    ("material_sample", "Material Sample"),
    ("mix_design", "Mix Design"),
    ("test_report", "Test Report"),
    ("certification", "Certificate or Certification"),
    ("manufacturer_data", "Manufacturer Data"),
    ("om_data", "Operation and Maintenance Data"),
    ("closeout", "Closeout Submittal"),
    ("mockup", "Mockup"),
    ("design_calculations", "Design Calculations"),
    ("coordination_drawings", "Coordination Drawings"),
    ("warranty", "Warranty"),
    ("informational", "Informational Submittal"),
    ("other", "Other"),
]

SUBMITTAL_STATUSES = [
    "unassigned", "required", "assigned", "requested", "received",
    "under_review", "approved", "approved_as_noted", "revise_and_resubmit",
    "rejected", "already_available", "not_required", "closed",
]

ORGANIZATION_TYPES = ["subcontractor", "vendor", "supplier", "manufacturer", "consultant"]

# The approved standard submittal folder structure (2026-08 spec, section
# 10) — every attachment belongs to exactly one of these four, and the
# application must never introduce alternate top-level folder names.
ATTACHMENT_FOLDERS = [
    ("from_vendor", "1. From Vendor"),
    ("to_engineer", "2. To Engineer"),
    ("from_engineer", "3. From Engineer"),
    ("final_approved", "4. Final Approved"),
]

PROJECT_ROLES = ["owner_admin", "admin", "assignee", "viewer"]


def hash_pdf_bytes(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------- numbering format ----
def _clean_spec_code(section_number: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", section_number or "")


def _strip_leading_spec_code(section_number: str, text_value: str) -> str:
    if not text_value or not section_number:
        return text_value
    text_value = text_value.strip()
    pattern_core = re.escape(section_number.strip())
    pattern_core = pattern_core.replace(r"\ ", r"\s+")
    pattern = rf"^\s*{pattern_core}\s*[-–—:]?\s*"
    stripped = re.sub(pattern, "", text_value, count=1, flags=re.IGNORECASE)
    return stripped.strip() or text_value


def _build_display_number(section_number: str, suffix: str, revision_letter: str = "A") -> str:
    """PSCC submittal numbering convention: D-<spec code>-<3-digit
    sequence>-<revision letter>, e.g. D-014523-001-A. `suffix` (the 3-digit
    sequence) is fixed for a submittal's lifetime; `revision_letter` is
    user-editable via the "Version" column and typically bumped on
    resubmittal (A -> B -> C...)."""
    return f"D-{_clean_spec_code(section_number)}-{suffix}-{revision_letter}"


# ---------------------------------------------------------------- users ----
def upsert_user(user_id: str, email: str, name: str, role: str = "member"):
    conn = _connect()
    conn.execute(text(
        """
        INSERT INTO users (id, email, name, role) VALUES (:id, :email, :name, :role)
        ON CONFLICT(id) DO UPDATE SET email=EXCLUDED.email, name=EXCLUDED.name, role=EXCLUDED.role
        """
    ), {"id": user_id, "email": email, "name": name, "role": role})
    conn.commit()
    conn.close()


def get_user_by_email(email: str):
    conn = _connect()
    row = conn.execute(text("SELECT id, email, name, role FROM users WHERE email = :email"),
                        {"email": email}).mappings().fetchone()
    conn.close()
    return dict(row) if row else None


def list_users():
    conn = _connect()
    rows = conn.execute(text("SELECT id, email, name, role FROM users ORDER BY name")).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def update_directory_info(email: str, job_title: str = None, department: str = None,
                           office: str = None, phone: str = None):
    """Fills in Operations Team Directory fields for an existing user.
    Only non-None fields are updated, so a partial edit doesn't blank out
    the rest."""
    fields = {k: v for k, v in {
        "job_title": job_title, "department": department, "office": office, "phone": phone,
    }.items() if v is not None}
    if not fields:
        return
    conn = _connect()
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    params = dict(fields)
    params["email"] = email
    conn.execute(text(f"UPDATE users SET {set_clause} WHERE email = :email"), params)
    conn.commit()
    conn.close()


def search_directory(query: str, limit: int = 10):
    """Operations Team Directory typeahead search — name, email, job
    title, department, or office, so inviting someone to a project is
    'search Charles' rather than typing an email address."""
    conn = _connect()
    like = f"%{query.lower()}%"
    rows = conn.execute(text(
        """
        SELECT id, email, name, job_title, department, office, phone
        FROM users
        WHERE LOWER(name) LIKE :like OR LOWER(email) LIKE :like
           OR LOWER(COALESCE(job_title, '')) LIKE :like
           OR LOWER(COALESCE(department, '')) LIKE :like
           OR LOWER(COALESCE(office, '')) LIKE :like
        ORDER BY name
        LIMIT :limit
        """
    ), {"like": like, "limit": limit}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def list_all_projects():
    conn = _connect()
    rows = conn.execute(text(
        "SELECT id, title, pinned, delete_requested_by FROM projects ORDER BY pinned DESC, created_at DESC"
    )).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def rename_project(project_id: str, new_title: str):
    conn = _connect()
    conn.execute(text("UPDATE projects SET title = :title WHERE id = :id"),
                 {"title": new_title, "id": project_id})
    conn.commit()
    conn.close()


def set_project_pinned(project_id: str, pinned: bool):
    conn = _connect()
    conn.execute(text("UPDATE projects SET pinned = :pinned WHERE id = :id"),
                 {"pinned": 1 if pinned else 0, "id": project_id})
    conn.commit()
    conn.close()


def request_delete_project(project_id: str, requested_by_email: str):
    conn = _connect()
    conn.execute(text(
        "UPDATE projects SET delete_requested_by = :by, delete_requested_at = :at WHERE id = :id"
    ), {"by": requested_by_email, "at": _now(), "id": project_id})
    conn.commit()
    conn.close()


def cancel_delete_request(project_id: str):
    conn = _connect()
    conn.execute(text(
        "UPDATE projects SET delete_requested_by = NULL, delete_requested_at = NULL WHERE id = :id"
    ), {"id": project_id})
    conn.commit()
    conn.close()


def delete_project(project_id: str):
    """Cascading delete — sections, their assignments, notifications, then
    the project row itself. Caller is responsible for removing files on disk."""
    conn = _connect()
    section_ids = [r["id"] for r in conn.execute(
        text("SELECT id FROM sections WHERE project_id = :pid"), {"pid": project_id}
    ).mappings().all()]
    for sid in section_ids:
        conn.execute(text("DELETE FROM assignments WHERE section_id = :sid"), {"sid": sid})
    conn.execute(text("DELETE FROM sections WHERE project_id = :pid"), {"pid": project_id})
    conn.execute(text("DELETE FROM notifications WHERE project_id = :pid"), {"pid": project_id})

    item_ids = [r["id"] for r in conn.execute(
        text("SELECT id FROM submittal_items WHERE project_id = :pid"), {"pid": project_id}
    ).mappings().all()]
    for iid in item_ids:
        conn.execute(text("DELETE FROM attachments WHERE submittal_item_id = :iid"), {"iid": iid})
        conn.execute(text("DELETE FROM comments WHERE submittal_item_id = :iid"), {"iid": iid})
    conn.execute(text("DELETE FROM submittal_items WHERE project_id = :pid"), {"pid": project_id})
    conn.execute(text("DELETE FROM specification_sections WHERE project_id = :pid"), {"pid": project_id})
    conn.execute(text("DELETE FROM organizations WHERE project_id = :pid"), {"pid": project_id})
    conn.execute(text("DELETE FROM project_members WHERE project_id = :pid"), {"pid": project_id})
    conn.execute(text("DELETE FROM activity_log WHERE project_id = :pid"), {"pid": project_id})

    conn.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id})
    conn.commit()
    conn.close()


# --------------------------------------------------------- notifications ----
def create_notification(user_email: str, project_id: str, message: str):
    conn = _connect()
    conn.execute(text(
        """
        INSERT INTO notifications (id, user_email, project_id, message, created_at, is_read)
        VALUES (:id, :email, :pid, :msg, :created, 0)
        """
    ), {"id": str(uuid.uuid4()), "email": user_email, "pid": project_id, "msg": message, "created": _now()})
    conn.commit()
    conn.close()


def get_notifications(user_email: str, unread_only: bool = False):
    conn = _connect()
    query = "SELECT * FROM notifications WHERE user_email = :email"
    if unread_only:
        query += " AND is_read = 0"
    query += " ORDER BY created_at DESC"
    rows = conn.execute(text(query), {"email": user_email}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def mark_notification_read(notification_id: str):
    conn = _connect()
    conn.execute(text("UPDATE notifications SET is_read = 1 WHERE id = :id"), {"id": notification_id})
    conn.commit()
    conn.close()


# ------------------------------------------------------ section flags ----
def create_section_flag(section_id: str, project_id: str, original_code: str,
                         embedded_code: str, description: str,
                         llm_explanation: str, suggested_code: str | None):
    conn = _connect()
    conn.execute(text(
        """
        INSERT INTO section_flags
            (id, section_id, project_id, original_code, embedded_code, description,
             llm_explanation, suggested_code, status)
        VALUES (:id, :sid, :pid, :orig, :embedded, :desc, :explain, :suggested, 'pending')
        """
    ), {
        "id": str(uuid.uuid4()), "sid": section_id, "pid": project_id, "orig": original_code,
        "embedded": embedded_code, "desc": description, "explain": llm_explanation,
        "suggested": suggested_code,
    })
    conn.commit()
    conn.close()


def get_pending_flags(project_id: str):
    conn = _connect()
    rows = conn.execute(text(
        "SELECT * FROM section_flags WHERE project_id = :pid AND status = 'pending'"
    ), {"pid": project_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def resolve_flag(flag_id: str, section_id: str, resolved_value: str, resolved_by: str):
    conn = _connect()
    conn.execute(text("UPDATE sections SET section_code = :val WHERE id = :sid"),
                 {"val": resolved_value, "sid": section_id})
    conn.execute(text(
        """
        UPDATE section_flags
        SET status = 'resolved', resolved_value = :val, resolved_by = :by, resolved_at = :at
        WHERE id = :id
        """
    ), {"val": resolved_value, "by": resolved_by, "at": _now(), "id": flag_id})
    conn.commit()
    conn.close()


# ------------------------------------------------------------ projects ----
def find_project_by_hash(file_hash: str):
    conn = _connect()
    row = conn.execute(text("SELECT * FROM projects WHERE file_hash = :h"),
                        {"h": file_hash}).mappings().fetchone()
    conn.close()
    return dict(row) if row else None


def create_project(title: str, file_hash: str, filename: str, uploaded_by: str) -> str:
    project_id = str(uuid.uuid4())
    conn = _connect()
    conn.execute(text(
        """
        INSERT INTO projects (id, title, file_hash, original_filename, uploaded_by, workflow_status, created_at)
        VALUES (:id, :title, :hash, :fname, :by, 'uploaded', :created)
        """
    ), {"id": project_id, "title": title, "hash": file_hash, "fname": filename,
        "by": uploaded_by, "created": _now()})
    conn.execute(text(
        """
        INSERT INTO project_members (project_id, user_email, role, status, invited_by, invited_at)
        VALUES (:pid, :email, 'owner_admin', 'active', :email, :created)
        """
    ), {"pid": project_id, "email": uploaded_by, "created": _now()})
    conn.commit()
    conn.close()
    return project_id


def update_project_status(project_id: str, status: str):
    conn = _connect()
    conn.execute(text("UPDATE projects SET workflow_status = :status WHERE id = :id"),
                 {"status": status, "id": project_id})
    conn.commit()
    conn.close()


def set_project_output(project_id: str, output_zip_path: str, qna_doc_id: str | None):
    conn = _connect()
    conn.execute(text(
        "UPDATE projects SET output_zip_path = :zip, qna_doc_id = :doc WHERE id = :id"
    ), {"zip": output_zip_path, "doc": qna_doc_id, "id": project_id})
    conn.commit()
    conn.close()


def set_source_pdf_path(project_id: str, path: str):
    conn = _connect()
    conn.execute(text("UPDATE projects SET source_pdf_path = :path WHERE id = :id"),
                 {"path": path, "id": project_id})
    conn.commit()
    conn.close()


def set_extraction_files(project_id: str, sections_xlsx_path: str, log_xlsx_path: str):
    conn = _connect()
    conn.execute(text(
        "UPDATE projects SET sections_xlsx_path = :sx, log_xlsx_path = :lx WHERE id = :id"
    ), {"sx": sections_xlsx_path, "lx": log_xlsx_path, "id": project_id})
    conn.commit()
    conn.close()


def set_project_info(project_id: str, info: dict):
    conn = _connect()
    conn.execute(text("UPDATE projects SET project_info_json = :info WHERE id = :id"),
                 {"info": json.dumps(info), "id": project_id})
    conn.commit()
    conn.close()


def get_project_info(project_id: str) -> dict:
    project = get_project(project_id)
    if not project or not project.get("project_info_json"):
        return {}
    try:
        return json.loads(project["project_info_json"])
    except (TypeError, ValueError):
        return {}


def get_project(project_id: str):
    conn = _connect()
    row = conn.execute(text("SELECT * FROM projects WHERE id = :id"),
                        {"id": project_id}).mappings().fetchone()
    conn.close()
    return dict(row) if row else None


# ------------------------------------------------------------ sections (legacy) ----
def save_sections(project_id: str, sections: list[dict]):
    conn = _connect()
    conn.execute(text("DELETE FROM sections WHERE project_id = :pid"), {"pid": project_id})
    for idx, row in enumerate(sections):
        section_id = str(uuid.uuid4())
        conn.execute(text(
            """
            INSERT INTO sections
                (id, project_id, section_code, description, order_index,
                 submittal_type, sub_vendor, due_date, received_date, float_days)
            VALUES (:id, :pid, :code, :desc, :idx, :type, :vendor, :due, :recv, :float)
            """
        ), {
            "id": section_id, "pid": project_id, "code": row.get("section_code", ""),
            "desc": row.get("description", ""), "idx": idx,
            "type": row.get("submittal_type"), "vendor": row.get("sub_vendor"),
            "due": row.get("due_date"), "recv": row.get("received_date"),
            "float": row.get("float_days"),
        })
        conn.execute(text(
            "INSERT INTO assignments (section_id, assigned_to, assigned_by, assigned_at) VALUES (:sid, NULL, NULL, NULL)"
        ), {"sid": section_id})
    conn.commit()
    conn.close()


def get_workspace(project_id: str):
    conn = _connect()
    rows = conn.execute(text(
        """
        SELECT s.id, s.section_code, s.description, s.order_index,
               s.submittal_type, s.sub_vendor, s.due_date, s.received_date, s.float_days,
               a.assigned_to
        FROM sections s
        LEFT JOIN assignments a ON a.section_id = s.id
        WHERE s.project_id = :pid
        ORDER BY s.order_index
        """
    ), {"pid": project_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


# =====================================================================
# Collaboration schema
# =====================================================================

# ------------------------------------------------------ project members ----
def get_project_role(project_id: str, user_email: str) -> str | None:
    """Only an 'active' membership row confers a role — 'pending' (a
    self-service access request awaiting admin approval) and 'inactive'
    both return None here, same as having no row at all."""
    conn = _connect()
    row = conn.execute(text(
        "SELECT role FROM project_members WHERE project_id = :pid AND user_email = :email AND status = 'active'"
    ), {"pid": project_id, "email": user_email}).mappings().fetchone()
    conn.close()
    return row["role"] if row else None


def get_project_membership_status(project_id: str, user_email: str) -> str | None:
    """Raw status ('active' / 'pending' / 'inactive') or None if there's no
    project_members row at all — lets callers distinguish 'never touched
    this project' from 'requested access, waiting on approval'."""
    conn = _connect()
    row = conn.execute(text(
        "SELECT status FROM project_members WHERE project_id = :pid AND user_email = :email"
    ), {"pid": project_id, "email": user_email}).mappings().fetchone()
    conn.close()
    return row["status"] if row else None


def request_project_access(project_id: str, user_email: str, requester_name: str = "",
                            requested_role: str = "assignee") -> bool:
    """Self-service access request — used when someone lands on a project
    they aren't a member of yet (e.g. they uploaded the exact spec book
    someone else already owns, or opened a shared project link). Creates
    a 'pending' project_members row and notifies the project's active
    admins; grants no role until an admin calls approve_project_access().
    Returns False as a no-op if they already have an active or pending row."""
    conn = _connect()
    existing = conn.execute(text(
        "SELECT status FROM project_members WHERE project_id = :pid AND user_email = :email"
    ), {"pid": project_id, "email": user_email}).mappings().fetchone()
    if existing and existing["status"] in ("active", "pending"):
        conn.close()
        return False

    conn.execute(text(
        """
        INSERT INTO project_members (project_id, user_email, role, status, invited_by, invited_at)
        VALUES (:pid, :email, :role, 'pending', :email, :at)
        ON CONFLICT(project_id, user_email) DO UPDATE
            SET role = EXCLUDED.role, status = 'pending', invited_by = EXCLUDED.invited_by, invited_at = EXCLUDED.invited_at
        """
    ), {"pid": project_id, "email": user_email, "role": requested_role, "at": _now()})
    conn.commit()
    conn.close()

    project = get_project(project_id)
    owners = [m["user_email"] for m in list_project_members(project_id)
              if m["role"] in ("owner_admin", "admin") and m["status"] == "active"]
    for owner_email in owners:
        create_notification(
            owner_email, project_id,
            f"{requester_name or user_email} requested to join {project['title']} — review it under Manage Team.",
        )
    log_activity(project_id, None, user_email, "access_requested", new_value={"requested_role": requested_role})
    return True


def approve_project_access(project_id: str, user_email: str, role: str, actor_email: str):
    if role not in PROJECT_ROLES:
        raise ValueError(f"Invalid role '{role}', must be one of {PROJECT_ROLES}")
    conn = _connect()
    conn.execute(text(
        "UPDATE project_members SET status = 'active', role = :role WHERE project_id = :pid AND user_email = :email"
    ), {"role": role, "pid": project_id, "email": user_email})
    conn.commit()
    conn.close()
    project = get_project(project_id)
    create_notification(
        user_email, project_id,
        f"Your request to join {project['title']} was approved — you're now a {role.replace('_', ' ').title()}.",
    )
    log_activity(project_id, None, actor_email, "access_approved", new_value={"user_email": user_email, "role": role})


def deny_project_access(project_id: str, user_email: str, actor_email: str):
    conn = _connect()
    conn.execute(text(
        "DELETE FROM project_members WHERE project_id = :pid AND user_email = :email AND status = 'pending'"
    ), {"pid": project_id, "email": user_email})
    conn.commit()
    conn.close()
    project = get_project(project_id)
    create_notification(user_email, project_id, f"Your request to join {project['title']} was declined.")
    log_activity(project_id, None, actor_email, "access_denied", new_value={"user_email": user_email})


def is_project_admin(project_id: str, user_email: str) -> bool:
    return get_project_role(project_id, user_email) in ("owner_admin", "admin")


def add_project_member(project_id: str, user_email: str, role: str, invited_by: str, status: str = "active"):
    if role not in PROJECT_ROLES:
        raise ValueError(f"Invalid role '{role}', must be one of {PROJECT_ROLES}")
    conn = _connect()
    conn.execute(text(
        """
        INSERT INTO project_members (project_id, user_email, role, status, invited_by, invited_at)
        VALUES (:pid, :email, :role, :status, :by, :at)
        ON CONFLICT(project_id, user_email) DO UPDATE SET role=EXCLUDED.role, status=EXCLUDED.status
        """
    ), {"pid": project_id, "email": user_email, "role": role, "status": status, "by": invited_by, "at": _now()})
    conn.commit()
    conn.close()
    log_activity(project_id, None, invited_by, "member_added",
                 new_value={"user_email": user_email, "role": role})


def update_member_role(project_id: str, user_email: str, new_role: str, actor_email: str):
    if new_role not in PROJECT_ROLES:
        raise ValueError(f"Invalid role '{new_role}', must be one of {PROJECT_ROLES}")
    conn = _connect()
    current = conn.execute(text(
        "SELECT role FROM project_members WHERE project_id = :pid AND user_email = :email"
    ), {"pid": project_id, "email": user_email}).mappings().fetchone()
    if current and current["role"] == "owner_admin" and new_role != "owner_admin":
        owner_count = conn.execute(text(
            "SELECT COUNT(*) AS c FROM project_members WHERE project_id = :pid AND role = 'owner_admin' AND status='active'"
        ), {"pid": project_id}).mappings().fetchone()["c"]
        if owner_count <= 1:
            conn.close()
            raise ValueError("Cannot demote the only remaining Owner Admin — promote someone else first.")
    old_role = current["role"] if current else None
    conn.execute(text(
        "UPDATE project_members SET role = :role WHERE project_id = :pid AND user_email = :email"
    ), {"role": new_role, "pid": project_id, "email": user_email})
    conn.commit()
    conn.close()
    log_activity(project_id, None, actor_email, "member_role_changed",
                 old_value={"role": old_role}, new_value={"role": new_role, "user_email": user_email})
    if new_role != old_role and user_email != actor_email:
        create_notification(
            user_email, project_id,
            f"Your role on this project was changed to {new_role.replace('_', ' ').title()}",
        )


def deactivate_project_member(project_id: str, user_email: str, actor_email: str):
    conn = _connect()
    target = conn.execute(text(
        "SELECT role FROM project_members WHERE project_id = :pid AND user_email = :email"
    ), {"pid": project_id, "email": user_email}).mappings().fetchone()
    if target and target["role"] == "owner_admin":
        owner_count = conn.execute(text(
            "SELECT COUNT(*) AS c FROM project_members WHERE project_id = :pid AND role = 'owner_admin' AND status = 'active'"
        ), {"pid": project_id}).mappings().fetchone()["c"]
        if owner_count <= 1:
            conn.close()
            raise ValueError("Cannot deactivate the only remaining Owner Admin — promote someone else first.")
    conn.execute(text(
        "UPDATE project_members SET status = 'inactive' WHERE project_id = :pid AND user_email = :email"
    ), {"pid": project_id, "email": user_email})
    conn.commit()
    conn.close()
    log_activity(project_id, None, actor_email, "member_deactivated", new_value={"user_email": user_email})


def remove_project_member(project_id: str, user_email: str, actor_email: str):
    conn = _connect()
    target = conn.execute(text(
        "SELECT role FROM project_members WHERE project_id = :pid AND user_email = :email"
    ), {"pid": project_id, "email": user_email}).mappings().fetchone()
    if target and target["role"] == "owner_admin":
        actor_row = conn.execute(text(
            "SELECT role FROM project_members WHERE project_id = :pid AND user_email = :email"
        ), {"pid": project_id, "email": actor_email}).mappings().fetchone()
        actor_role = actor_row["role"] if actor_row else None
        if actor_role != "owner_admin":
            conn.close()
            raise ValueError("Only an Owner Admin can remove another Owner Admin.")
        owner_count = conn.execute(text(
            "SELECT COUNT(*) AS c FROM project_members WHERE project_id = :pid AND role = 'owner_admin' AND status = 'active'"
        ), {"pid": project_id}).mappings().fetchone()["c"]
        if owner_count <= 1:
            conn.close()
            raise ValueError("Cannot remove the only remaining Owner Admin — promote someone else first.")
    conn.execute(text(
        "DELETE FROM project_members WHERE project_id = :pid AND user_email = :email"
    ), {"pid": project_id, "email": user_email})
    conn.commit()
    conn.close()
    log_activity(project_id, None, actor_email, "member_removed", new_value={"user_email": user_email})


def list_project_members(project_id: str):
    conn = _connect()
    rows = conn.execute(text(
        """
        SELECT pm.project_id, pm.user_email, pm.role, pm.status, pm.invited_by, pm.invited_at,
               u.name AS display_name, u.job_title AS company_role,
               (SELECT COUNT(*) FROM submittal_items si
                WHERE si.project_id = pm.project_id AND si.responsible_user_email = pm.user_email
                  AND si.is_archived = 0) AS assigned_count,
               (SELECT MAX(created_at) FROM activity_log al
                WHERE al.project_id = pm.project_id AND al.actor_email = pm.user_email) AS last_activity_at
        FROM project_members pm
        LEFT JOIN users u ON u.email = pm.user_email
        WHERE pm.project_id = :pid
        ORDER BY CASE pm.role WHEN 'owner_admin' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, u.name
        """
    ), {"pid": project_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def get_projects_for_member(user_email: str):
    conn = _connect()
    rows = conn.execute(text(
        """
        SELECT p.id, p.title, p.pinned, p.delete_requested_by, pm.role
        FROM projects p
        JOIN project_members pm ON pm.project_id = p.id
        WHERE pm.user_email = :email AND pm.status = 'active'
        ORDER BY p.pinned DESC, p.created_at DESC
        """
    ), {"email": user_email}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------- organizations ----
def create_organization(project_id: str, name: str, org_type: str = "subcontractor",
                         contact_name: str = None, email: str = None, phone: str = None,
                         trade: str = None) -> tuple[str, bool]:
    if org_type not in ORGANIZATION_TYPES:
        raise ValueError(f"Invalid organization_type '{org_type}', must be one of {ORGANIZATION_TYPES}")
    clean_name = name.strip()
    conn = _connect()
    existing = conn.execute(text(
        "SELECT id FROM organizations WHERE project_id = :pid AND is_active = 1 AND LOWER(organization_name) = LOWER(:name)"
    ), {"pid": project_id, "name": clean_name}).mappings().fetchone()
    if existing:
        conn.close()
        return existing["id"], False

    org_id = str(uuid.uuid4())
    conn.execute(text(
        """
        INSERT INTO organizations
            (id, project_id, organization_name, organization_type, primary_contact_name,
             email, phone, trade, is_active, created_at)
        VALUES (:id, :pid, :name, :type, :contact, :email, :phone, :trade, 1, :created)
        """
    ), {"id": org_id, "pid": project_id, "name": clean_name, "type": org_type, "contact": contact_name,
        "email": email, "phone": phone, "trade": trade, "created": _now()})
    conn.commit()
    conn.close()
    return org_id, True


def update_organization(org_id: str, **fields):
    allowed = {"organization_name", "organization_type", "primary_contact_name", "email", "phone", "trade"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    conn = _connect()
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    params = dict(fields)
    params["id"] = org_id
    conn.execute(text(f"UPDATE organizations SET {set_clause} WHERE id = :id"), params)
    conn.commit()
    conn.close()


def search_organizations(project_id: str, query: str = ""):
    conn = _connect()
    if query:
        like = f"%{query.lower()}%"
        rows = conn.execute(text(
            """
            SELECT * FROM organizations
            WHERE project_id = :pid AND is_active = 1
              AND (LOWER(organization_name) LIKE :like OR LOWER(COALESCE(trade,'')) LIKE :like)
            ORDER BY organization_name
            """
        ), {"pid": project_id, "like": like}).mappings().all()
    else:
        rows = conn.execute(text(
            "SELECT * FROM organizations WHERE project_id = :pid AND is_active = 1 ORDER BY organization_name"
        ), {"pid": project_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def list_all_organizations(project_id: str):
    conn = _connect()
    rows = conn.execute(text(
        "SELECT * FROM organizations WHERE project_id = :pid ORDER BY is_active DESC, organization_name"
    ), {"pid": project_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def reactivate_organization(org_id: str):
    conn = _connect()
    conn.execute(text("UPDATE organizations SET is_active = 1 WHERE id = :id"), {"id": org_id})
    conn.commit()
    conn.close()


def deactivate_organization(org_id: str):
    conn = _connect()
    conn.execute(text("UPDATE organizations SET is_active = 0 WHERE id = :id"), {"id": org_id})
    conn.commit()
    conn.close()


# ------------------------------------------------------ specification sections ----
def create_specification_section(project_id: str, section_number: str, section_name: str = "",
                                   section_text_reference: str = "", order_index: int = 0) -> str:
    section_id = str(uuid.uuid4())
    conn = _connect()
    conn.execute(text(
        """
        INSERT INTO specification_sections
            (id, project_id, section_number, section_name, section_text_reference, order_index, created_at)
        VALUES (:id, :pid, :num, :name, :ref, :idx, :created)
        """
    ), {"id": section_id, "pid": project_id, "num": section_number, "name": section_name,
        "ref": section_text_reference, "idx": order_index, "created": _now()})
    conn.commit()
    conn.close()
    return section_id


def get_specification_sections(project_id: str):
    conn = _connect()
    rows = conn.execute(text(
        "SELECT * FROM specification_sections WHERE project_id = :pid ORDER BY order_index"
    ), {"pid": project_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def set_section_summary(section_id: str, summary: str, model: str = None, version: str = None):
    conn = _connect()
    conn.execute(text(
        """
        UPDATE specification_sections
        SET section_summary = :summary, summary_generated_at = :at, summary_model = :model, summary_version = :version
        WHERE id = :id
        """
    ), {"summary": summary, "at": _now(), "model": model, "version": version, "id": section_id})
    conn.commit()
    conn.close()


def assign_section(section_id: str, user_email: str | None, actor_email: str):
    """Section-level internal assignment — applies to every submittal under
    this section unless a specific item overrides responsible_user_email.
    Passing user_email=None clears the assignment."""
    conn = _connect()
    section = conn.execute(text("SELECT * FROM specification_sections WHERE id = :id"),
                            {"id": section_id}).mappings().fetchone()
    if not section:
        conn.close()
        raise ValueError("specification section not found")
    old_assignee = section["assigned_user_email"]
    conn.execute(text("UPDATE specification_sections SET assigned_user_email = :email WHERE id = :id"),
                 {"email": user_email, "id": section_id})
    conn.commit()
    conn.close()
    log_activity(section["project_id"], None, actor_email, "section_assigned",
                 old_value={"assigned_user_email": old_assignee},
                 new_value={"assigned_user_email": user_email, "section_number": section["section_number"]})
    if user_email and user_email != old_assignee:
        create_notification(
            user_email, section["project_id"],
            f"You were assigned Section {section['section_number']}: {section['section_name'] or ''}".strip(),
        )


def set_section_not_required(section_id: str, reason: str | None, actor_email: str, not_required: bool = True):
    """Marks a section Not Required (collapsed, kept visible/searchable, not
    deleted) with a recorded reason, or reactivates it back to 'active'."""
    conn = _connect()
    section = conn.execute(text("SELECT * FROM specification_sections WHERE id = :id"),
                            {"id": section_id}).mappings().fetchone()
    if not section:
        conn.close()
        raise ValueError("specification section not found")
    new_status = "not_required" if not_required else "active"
    conn.execute(text(
        "UPDATE specification_sections SET status = :status, not_required_reason = :reason WHERE id = :id"
    ), {"status": new_status, "reason": reason if not_required else None, "id": section_id})
    conn.commit()
    conn.close()
    log_activity(section["project_id"], None, actor_email,
                 "section_marked_not_required" if not_required else "section_reactivated",
                 old_value={"status": section["status"]},
                 new_value={"status": new_status, "reason": reason, "section_number": section["section_number"]})


def update_section_text_reference(section_id: str, text_value: str):
    conn = _connect()
    conn.execute(text("UPDATE specification_sections SET section_text_reference = :text WHERE id = :id"),
                 {"text": text_value, "id": section_id})
    conn.commit()
    conn.close()


def sync_section_number(project_id: str, old_number: str, new_number: str):
    conn = _connect()
    row = conn.execute(text(
        "SELECT id FROM specification_sections WHERE project_id = :pid AND section_number = :num"
    ), {"pid": project_id, "num": old_number}).mappings().fetchone()
    if not row:
        conn.close()
        return
    conn.execute(text("UPDATE specification_sections SET section_number = :num WHERE id = :id"),
                 {"num": new_number, "id": row["id"]})
    items = conn.execute(text(
        "SELECT id, suffix, revision_letter FROM submittal_items WHERE specification_section_id = :sid"
    ), {"sid": row["id"]}).mappings().all()
    for item in items:
        conn.execute(text("UPDATE submittal_items SET display_number = :dn WHERE id = :id"),
                     {"dn": _build_display_number(new_number, item["suffix"], item["revision_letter"]), "id": item["id"]})
    conn.commit()
    conn.close()


# ------------------------------------------------------------ submittal items ----
def _next_suffix(project_id: str, specification_section_id: str, conn) -> str:
    existing = conn.execute(text(
        "SELECT suffix FROM submittal_items WHERE specification_section_id = :sid"
    ), {"sid": specification_section_id}).mappings().all()
    used = {r["suffix"] for r in existing}
    i = 1
    while True:
        candidate = f"{i:03d}"
        if candidate not in used:
            return candidate
        i += 1


def _backfill_section_order_index(conn, specification_section_id: str):
    """Assigns a real order_index to any rows in this section that still
    have NULL (e.g. inserted by migrate_legacy_sections_to_items after the
    one-time startup backfill in init_db() already ran). Postgres sorts
    NULLs last by default, so leaving these unbackfilled would let a
    freshly-added item's low order_index jump ahead of them — this must
    run before anything computes MAX(order_index) or swaps neighbors."""
    null_rows = conn.execute(text(
        "SELECT id FROM submittal_items WHERE specification_section_id = :sid AND order_index IS NULL ORDER BY suffix"
    ), {"sid": specification_section_id}).mappings().all()
    if not null_rows:
        return
    start = conn.execute(text(
        "SELECT COALESCE(MAX(order_index), -1) + 1 AS n FROM submittal_items WHERE specification_section_id = :sid"
    ), {"sid": specification_section_id}).mappings().fetchone()["n"]
    for i, row in enumerate(null_rows):
        conn.execute(text("UPDATE submittal_items SET order_index = :o WHERE id = :id"),
                     {"o": start + i, "id": row["id"]})


def create_submittal_item(project_id: str, specification_section_id: str, title: str,
                           created_by: str, submittal_type: str = None,
                           organization_id: str = None, responsible_user_email: str = None,
                           status: str = "unassigned", due_date: str = None, notes: str = None) -> str:
    conn = _connect()
    section = conn.execute(text(
        "SELECT section_number FROM specification_sections WHERE id = :sid"
    ), {"sid": specification_section_id}).mappings().fetchone()
    if not section:
        conn.close()
        raise ValueError("specification_section_id not found")

    suffix = _next_suffix(project_id, specification_section_id, conn)
    display_number = _build_display_number(section["section_number"], suffix)
    _backfill_section_order_index(conn, specification_section_id)
    next_order = conn.execute(text(
        "SELECT COALESCE(MAX(order_index), -1) + 1 AS n FROM submittal_items WHERE specification_section_id = :sid"
    ), {"sid": specification_section_id}).mappings().fetchone()["n"]
    item_id = str(uuid.uuid4())
    now = _now()
    conn.execute(text(
        """
        INSERT INTO submittal_items
            (id, project_id, specification_section_id, suffix, display_number, title,
             submittal_type, organization_id, responsible_user_email, status, due_date,
             notes, is_archived, created_by, created_at, updated_at, order_index)
        VALUES (:id, :pid, :sid, :suffix, :dn, :title, :type, :org, :resp, :status, :due,
                :notes, 0, :by, :now, :now, :order_index)
        """
    ), {"id": item_id, "pid": project_id, "sid": specification_section_id, "suffix": suffix,
        "dn": display_number, "title": title, "type": submittal_type, "org": organization_id,
        "resp": responsible_user_email, "status": status, "due": due_date, "notes": notes,
        "by": created_by, "now": now, "order_index": next_order})
    conn.commit()
    conn.close()
    log_activity(project_id, item_id, created_by, "submittal_created",
                 new_value={"title": title, "display_number": display_number})
    if responsible_user_email:
        create_notification(
            responsible_user_email, project_id,
            f"You were assigned to {display_number}: {title}",
        )
    return item_id


def get_submittal_item(item_id: str):
    conn = _connect()
    row = conn.execute(text("SELECT * FROM submittal_items WHERE id = :id"),
                        {"id": item_id}).mappings().fetchone()
    conn.close()
    return dict(row) if row else None


def can_edit_section(section_id: str, user_email: str) -> bool:
    """Admins can edit any section; an Assignee can edit only sections
    where they're the section-level assigned_user_email (2026-08
    collaborative-workspace spec, section 18 — view everything, edit only
    your own). Viewers and non-members can never edit."""
    conn = _connect()
    section = conn.execute(text(
        "SELECT project_id, assigned_user_email FROM specification_sections WHERE id = :id"
    ), {"id": section_id}).mappings().fetchone()
    conn.close()
    if not section:
        return False
    role = get_project_role(section["project_id"], user_email)
    if role in ("owner_admin", "admin"):
        return True
    return role == "assignee" and section["assigned_user_email"] == user_email


def get_submittal_items_for_section(specification_section_id: str, include_archived: bool = False):
    conn = _connect()
    query = "SELECT * FROM submittal_items WHERE specification_section_id = :sid"
    if not include_archived:
        query += " AND is_archived = 0"
    query += " ORDER BY order_index, suffix"
    rows = conn.execute(text(query), {"sid": specification_section_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def get_submittal_items_for_project(project_id: str, include_archived: bool = False):
    conn = _connect()
    query = "SELECT * FROM submittal_items WHERE project_id = :pid"
    if not include_archived:
        query += " AND is_archived = 0"
    query += " ORDER BY specification_section_id, order_index, suffix"
    rows = conn.execute(text(query), {"pid": project_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


_UPDATABLE_ITEM_FIELDS = {
    "title", "submittal_type", "submittal_type_other", "organization_id",
    "responsible_user_email", "status", "status_reason", "due_date", "notes",
    "revision_letter",
}


def update_submittal_item(item_id: str, actor_email: str, **fields):
    fields = {k: v for k, v in fields.items() if k in _UPDATABLE_ITEM_FIELDS}
    if not fields:
        return

    conn = _connect()
    before = conn.execute(text("SELECT * FROM submittal_items WHERE id = :id"),
                           {"id": item_id}).mappings().fetchone()
    if not before:
        conn.close()
        raise ValueError("submittal item not found")
    before = dict(before)

    if "revision_letter" in fields:
        # Version/revision letter is part of display_number (e.g.
        # D-014523-001-A) — keep the two in sync on every edit.
        section = conn.execute(text(
            "SELECT section_number FROM specification_sections WHERE id = :sid"
        ), {"sid": before["specification_section_id"]}).mappings().fetchone()
        fields["display_number"] = _build_display_number(
            section["section_number"], before["suffix"], fields["revision_letter"]
        )

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    params = dict(fields)
    params["updated_at"] = _now()
    params["id"] = item_id
    conn.execute(text(f"UPDATE submittal_items SET {set_clause}, updated_at = :updated_at WHERE id = :id"), params)
    conn.commit()
    conn.close()

    old_value = {k: before.get(k) for k in fields}
    log_activity(before["project_id"], item_id, actor_email, "submittal_updated",
                 old_value=old_value, new_value=fields)

    if "responsible_user_email" in fields:
        old_assignee = before.get("responsible_user_email")
        new_assignee = fields["responsible_user_email"]
        if new_assignee and new_assignee != old_assignee:
            create_notification(new_assignee, before["project_id"],
                                 f"You were assigned to {before['display_number']}: {before['title']}")
        if old_assignee and old_assignee != new_assignee:
            create_notification(old_assignee, before["project_id"],
                                 f"You were unassigned from {before['display_number']}: {before['title']}")

    if "status" in fields:
        new_status = fields["status"]
        status_label = new_status.replace("_", " ").title()
        if new_status == "under_review":
            _notify_relevant_parties(
                before["project_id"], item_id, actor_email,
                f"{actor_email} submitted {before['display_number']} for review",
            )
        else:
            _notify_relevant_parties(
                before["project_id"], item_id, actor_email,
                f"Status of {before['display_number']} changed to {status_label}",
            )
        if new_status == "already_available":
            log_activity(before["project_id"], item_id, actor_email, "marked_already_available")
        elif new_status == "not_required":
            log_activity(before["project_id"], item_id, actor_email, "marked_not_required",
                         new_value={"reason": fields.get("status_reason")})


def move_submittal_item(item_id: str, direction: str, actor_email: str):
    """Swaps this item's order_index with its neighbor above/below within
    the same section — admin-only manual row reordering. No-ops silently
    if already at the top/bottom (nothing to swap with)."""
    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' or 'down'")

    conn = _connect()
    item = conn.execute(text("SELECT * FROM submittal_items WHERE id = :id"),
                         {"id": item_id}).mappings().fetchone()
    if not item:
        conn.close()
        raise ValueError("submittal item not found")

    _backfill_section_order_index(conn, item["specification_section_id"])
    siblings = conn.execute(text(
        """
        SELECT id, order_index FROM submittal_items
        WHERE specification_section_id = :sid AND is_archived = 0
        ORDER BY order_index, suffix
        """
    ), {"sid": item["specification_section_id"]}).mappings().all()
    ids = [s["id"] for s in siblings]
    idx = ids.index(item_id)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(ids):
        conn.close()
        return  # already at the boundary

    other = siblings[swap_idx]
    this_order = siblings[idx]["order_index"]
    conn.execute(text("UPDATE submittal_items SET order_index = :o WHERE id = :id"),
                 {"o": other["order_index"], "id": item_id})
    conn.execute(text("UPDATE submittal_items SET order_index = :o WHERE id = :id"),
                 {"o": this_order, "id": other["id"]})
    conn.commit()
    conn.close()


def archive_submittal_item(item_id: str, actor_email: str):
    conn = _connect()
    row = conn.execute(text("SELECT project_id FROM submittal_items WHERE id = :id"),
                        {"id": item_id}).mappings().fetchone()
    conn.execute(text("UPDATE submittal_items SET is_archived = 1, updated_at = :now WHERE id = :id"),
                 {"now": _now(), "id": item_id})
    conn.commit()
    conn.close()
    if row:
        log_activity(row["project_id"], item_id, actor_email, "submittal_archived")


def delete_submittal_item(item_id: str, actor_email: str):
    conn = _connect()
    row = conn.execute(text("SELECT project_id FROM submittal_items WHERE id = :id"),
                        {"id": item_id}).mappings().fetchone()
    conn.execute(text("DELETE FROM attachments WHERE submittal_item_id = :id"), {"id": item_id})
    conn.execute(text("DELETE FROM comments WHERE submittal_item_id = :id"), {"id": item_id})
    conn.execute(text("DELETE FROM submittal_items WHERE id = :id"), {"id": item_id})
    conn.commit()
    conn.close()
    if row:
        log_activity(row["project_id"], item_id, actor_email, "submittal_deleted")




# ------------------------------------------------------------------ activity log ----
def _notify_relevant_parties(project_id: str, item_id: str, actor_email: str, message: str):
    conn = _connect()
    item = conn.execute(text(
        "SELECT responsible_user_email FROM submittal_items WHERE id = :id"
    ), {"id": item_id}).mappings().fetchone()
    responsible = item["responsible_user_email"] if item else None
    owners = conn.execute(text(
        "SELECT user_email FROM project_members WHERE project_id = :pid AND role IN ('owner_admin', 'admin') AND status = 'active'"
    ), {"pid": project_id}).mappings().all()
    conn.close()

    if responsible and responsible != actor_email:
        create_notification(responsible, project_id, message)
        return
    for o in owners:
        if o["user_email"] != actor_email:
            create_notification(o["user_email"], project_id, message)


def log_activity(project_id: str, submittal_item_id: str | None, actor_email: str,
                  action_type: str, old_value: dict = None, new_value: dict = None):
    conn = _connect()
    conn.execute(text(
        """
        INSERT INTO activity_log
            (id, project_id, submittal_item_id, actor_email, action_type, old_value, new_value, created_at)
        VALUES (:id, :pid, :item, :actor, :action, :old, :new, :created)
        """
    ), {
        "id": str(uuid.uuid4()), "pid": project_id, "item": submittal_item_id, "actor": actor_email,
        "action": action_type,
        "old": json.dumps(old_value) if old_value is not None else None,
        "new": json.dumps(new_value) if new_value is not None else None,
        "created": _now(),
    })
    conn.commit()
    conn.close()


def get_activity_for_project(project_id: str, limit: int = 200):
    conn = _connect()
    rows = conn.execute(text(
        "SELECT * FROM activity_log WHERE project_id = :pid ORDER BY created_at DESC LIMIT :limit"
    ), {"pid": project_id, "limit": limit}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def get_activity_for_item(submittal_item_id: str):
    conn = _connect()
    rows = conn.execute(text(
        "SELECT * FROM activity_log WHERE submittal_item_id = :id ORDER BY created_at DESC"
    ), {"id": submittal_item_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ attachments ----
def create_attachment(submittal_item_id: str, project_id: str, file_path: str,
                       original_filename: str, uploaded_by: str, description: str,
                       folder: str = "from_vendor", vendor_version: str = None,
                       formal_revision: str = None) -> str:
    if folder not in dict(ATTACHMENT_FOLDERS):
        raise ValueError(f"Invalid folder '{folder}', must be one of {[k for k, _ in ATTACHMENT_FOLDERS]}")
    att_id = str(uuid.uuid4())
    conn = _connect()
    conn.execute(text(
        """
        INSERT INTO attachments
            (id, submittal_item_id, project_id, file_path, original_filename, uploaded_by, uploaded_at,
             folder, description, vendor_version, formal_revision)
        VALUES (:id, :item, :pid, :path, :fname, :by, :at, :folder, :desc, :vversion, :frevision)
        """
    ), {"id": att_id, "item": submittal_item_id, "pid": project_id, "path": file_path,
        "fname": original_filename, "by": uploaded_by, "at": _now(), "folder": folder,
        "desc": description, "vversion": vendor_version, "frevision": formal_revision})
    conn.commit()
    conn.close()
    log_activity(project_id, submittal_item_id, uploaded_by, "file_uploaded",
                 new_value={"filename": original_filename})
    _notify_relevant_parties(project_id, submittal_item_id, uploaded_by,
                              f"{uploaded_by} uploaded a file: {original_filename}")
    return att_id


def list_attachments(submittal_item_id: str):
    conn = _connect()
    rows = conn.execute(text(
        "SELECT * FROM attachments WHERE submittal_item_id = :id ORDER BY uploaded_at DESC"
    ), {"id": submittal_item_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def get_attachment(attachment_id: str):
    conn = _connect()
    row = conn.execute(text("SELECT * FROM attachments WHERE id = :id"),
                        {"id": attachment_id}).mappings().fetchone()
    conn.close()
    return dict(row) if row else None


# ------------------------------------------------------------------ comments ----
def create_comment(submittal_item_id: str, project_id: str, author_email: str, body: str) -> str:
    comment_id = str(uuid.uuid4())
    conn = _connect()
    conn.execute(text(
        """
        INSERT INTO comments (id, submittal_item_id, project_id, author_email, body, created_at)
        VALUES (:id, :item, :pid, :author, :body, :created)
        """
    ), {"id": comment_id, "item": submittal_item_id, "pid": project_id, "author": author_email,
        "body": body, "created": _now()})
    conn.commit()
    conn.close()
    log_activity(project_id, submittal_item_id, author_email, "comment_added")
    _notify_relevant_parties(project_id, submittal_item_id, author_email,
                              f"{author_email} added a comment")
    return comment_id


def list_comments(submittal_item_id: str):
    conn = _connect()
    rows = conn.execute(text(
        "SELECT * FROM comments WHERE submittal_item_id = :id ORDER BY created_at"
    ), {"id": submittal_item_id}).mappings().all()
    conn.close()
    return [dict(r) for r in rows]


def clean_legacy_titles(project_id: str):
    conn = _connect()
    sections = conn.execute(text(
        "SELECT id, section_number, section_name FROM specification_sections WHERE project_id = :pid"
    ), {"pid": project_id}).mappings().all()
    changed_sections = 0
    for s in sections:
        cleaned = _strip_leading_spec_code(s["section_number"], s["section_name"] or "")
        if cleaned != s["section_name"]:
            conn.execute(text("UPDATE specification_sections SET section_name = :name WHERE id = :id"),
                         {"name": cleaned, "id": s["id"]})
            changed_sections += 1

    items = conn.execute(text(
        """
        SELECT si.id, si.title, ss.section_number
        FROM submittal_items si
        JOIN specification_sections ss ON ss.id = si.specification_section_id
        WHERE si.project_id = :pid
        """
    ), {"pid": project_id}).mappings().all()
    changed_items = 0
    for it in items:
        cleaned = _strip_leading_spec_code(it["section_number"], it["title"] or "")
        if cleaned != it["title"]:
            conn.execute(text("UPDATE submittal_items SET title = :title WHERE id = :id"),
                         {"title": cleaned, "id": it["id"]})
            changed_items += 1

    conn.commit()
    conn.close()
    return {"sections_cleaned": changed_sections, "items_cleaned": changed_items}


# ------------------------------------------------------------------ migration ----
def migrate_legacy_sections_to_items(project_id: str, actor_email: str = "system"):
    """One-time-per-project copy of the legacy `sections` + `assignments`
    rows into `specification_sections` + `submittal_items`. Safe to call
    multiple times — no-ops if projects.legacy_migrated_at is already set."""
    conn = _connect()
    project = conn.execute(text("SELECT * FROM projects WHERE id = :id"),
                            {"id": project_id}).mappings().fetchone()
    if not project:
        conn.close()
        return
    if project["legacy_migrated_at"]:
        conn.close()
        return

    legacy_rows = conn.execute(text(
        """
        SELECT s.*, a.assigned_to
        FROM sections s
        LEFT JOIN assignments a ON a.section_id = s.id
        WHERE s.project_id = :pid
        ORDER BY s.order_index
        """
    ), {"pid": project_id}).mappings().all()

    org_cache = {}

    for idx, row in enumerate(legacy_rows):
        row = dict(row)
        section_id = str(uuid.uuid4())
        section_title = _strip_leading_spec_code(
            row["section_code"], (row.get("description") or "").strip()
        ) or row["section_code"]
        conn.execute(text(
            """
            INSERT INTO specification_sections
                (id, project_id, section_number, section_name, section_text_reference, order_index, created_at)
            VALUES (:id, :pid, :num, :name, :ref, :idx, :created)
            """
        ), {"id": section_id, "pid": project_id, "num": row["section_code"], "name": section_title,
            "ref": row.get("description") or "", "idx": idx, "created": _now()})

        org_id = None
        vendor_name = (row.get("sub_vendor") or "").strip()
        if vendor_name:
            if vendor_name in org_cache:
                org_id = org_cache[vendor_name]
            else:
                existing_org = conn.execute(text(
                    "SELECT id FROM organizations WHERE project_id = :pid AND organization_name = :name"
                ), {"pid": project_id, "name": vendor_name}).mappings().fetchone()
                if existing_org:
                    org_id = existing_org["id"]
                else:
                    org_id = str(uuid.uuid4())
                    conn.execute(text(
                        """
                        INSERT INTO organizations
                            (id, project_id, organization_name, organization_type, is_active, created_at)
                        VALUES (:id, :pid, :name, 'subcontractor', 1, :created)
                        """
                    ), {"id": org_id, "pid": project_id, "name": vendor_name, "created": _now()})
                org_cache[vendor_name] = org_id

        item_id = str(uuid.uuid4())
        display_number = _build_display_number(row["section_code"], "001")
        legacy_type = (row.get("submittal_type") or "").strip()
        status = "assigned" if row.get("assigned_to") else "unassigned"
        now = _now()
        conn.execute(text(
            """
            INSERT INTO submittal_items
                (id, project_id, specification_section_id, suffix, display_number, title,
                 submittal_type, organization_id, responsible_user_email, status, due_date,
                 notes, is_archived, created_by, created_at, updated_at, order_index)
            VALUES (:id, :pid, :sid, '001', :dn, :title, :type, :org, :resp, :status, :due,
                    NULL, 0, :by, :now, :now, 0)
            """
        ), {
            "id": item_id, "pid": project_id, "sid": section_id, "dn": display_number,
            "title": _strip_leading_spec_code(
                row["section_code"], row.get("description") or row["section_code"]
            ),
            "type": legacy_type or None, "org": org_id, "resp": row.get("assigned_to"),
            "status": status, "due": row.get("due_date"), "by": actor_email, "now": now,
        })

    conn.execute(text("UPDATE projects SET legacy_migrated_at = :at WHERE id = :id"),
                 {"at": _now(), "id": project_id})
    conn.commit()
    conn.close()
    log_activity(project_id, None, actor_email, "legacy_data_migrated",
                 new_value={"section_count": len(legacy_rows)})
