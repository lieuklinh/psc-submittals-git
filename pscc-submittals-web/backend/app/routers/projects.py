import base64
import os
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from .. import config, db, extraction
from ..deps import get_current_user
from ..schemas import ConfirmProjectRequest, RenamePinRequest

router = APIRouter(prefix="/api/projects", tags=["projects"])

# In-memory extraction job tracker, keyed by job_id — {status, steps,
# project_id, error}. Written by the background thread in
# _run_confirm_job, read by the polling endpoint below. Good enough for a
# single-instance deployment (this whole app has no other multi-instance
# state either); doesn't survive a process restart, which just means an
# in-flight extraction's progress view goes stale — the extraction itself
# still completes and the project still gets created.
_confirm_jobs: dict[str, dict] = {}


def _require_role(project_id: str, user_email: str, allowed: set[str]):
    role = db.get_project_role(project_id, user_email)
    if role not in allowed:
        raise HTTPException(403, "You don't have permission to do this.")
    return role


@router.get("")
def list_my_projects(user=Depends(get_current_user)):
    return db.get_projects_for_member(user["email"])


@router.post("/scan")
async def scan_pdf(file: UploadFile = File(...), user=Depends(get_current_user)):
    """Step 1 of upload: stash the PDF, compute its hash, and return
    irregular section codes + auto-extracted project info for the client
    to review before /confirm actually creates the project and runs
    extraction. Mirrors handle_pdf_upload's first half in the Streamlit app."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    pdf_bytes = await file.read()
    file_hash = db.hash_pdf_bytes(pdf_bytes)

    existing = db.find_project_by_hash(file_hash)
    if existing:
        # No longer auto-granted admin (2026-07-22 meeting notes, item 2):
        # whoever has this exact file might not be a legitimate team
        # member. If they're not already an active member, the workspace
        # endpoint below returns the full read-only view and the frontend
        # shows a "Request to join" gate instead.
        return {"status": "existing", "project": existing}

    scan_id = str(uuid.uuid4())
    scan_path = config.SCANS_DIR / f"{scan_id}.pdf"
    with open(scan_path, "wb") as f:
        f.write(pdf_bytes)

    irregular_codes = extraction.scan_pdf_for_irregular_codes(pdf_bytes)
    try:
        project_info, _ = extraction.extract_project_info_via_openai(
            pdf_bytes, config.OPENAI_API_KEY, config.OPENAI_MODEL
        )
    except Exception as e:
        project_info = {k: "" for k in extraction.PROJECT_INFO_SCHEMA_KEYS}
        project_info["_error"] = str(e)

    return {
        "status": "new",
        "scan_id": scan_id,
        "file_hash": file_hash,
        "filename": file.filename,
        "irregular_codes": irregular_codes,
        "project_info": project_info,
    }


def _run_confirm_job(job_id: str, scan_id: str, filename: str, project_info: dict,
                      code_corrections: dict, user: dict):
    """Runs the full extraction pipeline in a background thread, appending
    a human-readable line to _confirm_jobs[job_id]['steps'] before each
    stage — the same step labels and order as the Streamlit app's
    `st.status(...)` block, so the two UIs read identically."""
    job = _confirm_jobs[job_id]

    def add_step(label: str):
        job["steps"].append(label)

    project_id = None
    try:
        scan_path = config.SCANS_DIR / f"{scan_id}.pdf"
        if not scan_path.exists():
            raise RuntimeError("Scan not found or already consumed — re-upload the PDF.")
        with open(scan_path, "rb") as f:
            pdf_bytes = f.read()

        file_hash = db.hash_pdf_bytes(pdf_bytes)
        title = os.path.splitext(filename)[0]
        project_id = db.create_project(title=title, file_hash=file_hash, filename=filename, uploaded_by=user["email"])
        job["project_id"] = project_id

        source_path = config.UPLOADS_DIR / f"{project_id}.pdf"
        with open(source_path, "wb") as f:
            f.write(pdf_bytes)
        db.set_source_pdf_path(project_id, str(source_path))

        for lead_email in config.TEAM_LEAD_EMAILS:
            if lead_email and lead_email != user["email"]:
                db.add_project_member(project_id, lead_email, "admin", user["email"])
            db.create_notification(lead_email, project_id, f"{user['name']} uploaded a new project: {title}")

        db.update_project_status(project_id, "extracting")
        b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        add_step("Extracting submittal sections...")
        sections_bytes = extraction.call_extract_sections(filename, b64)

        add_step("Building submittal log...")
        log_bytes = extraction.call_extract_log(filename, b64)

        add_step("Generating folder structure and transmittals...")
        structure_zip = extraction.call_create_structure(filename, b64, project_info)

        add_step("Populating the workspace...")
        parsed_sections = extraction.parse_log_for_workspace(log_bytes)
        for s in parsed_sections:
            if s["section_code"] in code_corrections:
                s["section_code"] = code_corrections[s["section_code"]]
        db.save_sections(project_id, parsed_sections)

        anomalies = extraction.detect_section_code_anomalies(parsed_sections)
        if anomalies:
            add_step(f"Reviewing {len(anomalies)} section(s) with formatting quirks...")
            saved_rows = {r["section_code"]: r for r in db.get_workspace(project_id)}
            for a in anomalies:
                matching_row = saved_rows.get(a["section_code"])
                if not matching_row:
                    continue
                explanation, suggested = extraction.explain_anomaly_via_openai(
                    a["section_code"], a["embedded_code"], a["description"],
                    config.OPENAI_API_KEY, config.OPENAI_MODEL,
                )
                db.create_section_flag(
                    matching_row["id"], project_id, a["section_code"], a["embedded_code"],
                    a["description"], explanation, suggested,
                )

        add_step("Setting up the collaborative workspace...")
        db.migrate_legacy_sections_to_items(project_id, actor_email=user["email"])

        sections = db.get_specification_sections(project_id)
        text_by_section = extraction.extract_section_full_text(pdf_bytes, sections)
        for section_id, chunk in text_by_section.items():
            db.update_section_text_reference(section_id, chunk)

        add_step("Summarizing each section for the workspace table...")
        summary_ok, summary_failed = 0, 0
        for sec in db.get_specification_sections(project_id):
            if (sec.get("section_summary") or "").strip():
                continue
            summary = extraction.generate_section_summary(sec, config.OPENAI_API_KEY, config.OPENAI_MODEL)
            if summary:
                db.set_section_summary(sec["id"], summary, model=config.OPENAI_MODEL, version="v1")
                summary_ok += 1
            else:
                summary_failed += 1
        if summary_failed:
            add_step(
                f"Summarized {summary_ok} section(s); {summary_failed} couldn't be summarized "
                f"(no captured text or no OpenAI key) — these can be retried from the workspace table."
            )

        add_step("Packaging results...")
        sections_path = config.OUTPUTS_DIR / f"{project_id}_sections.xlsx"
        log_path = config.OUTPUTS_DIR / f"{project_id}_log.xlsx"
        with open(sections_path, "wb") as f:
            f.write(sections_bytes)
        with open(log_path, "wb") as f:
            f.write(log_bytes)
        db.set_extraction_files(project_id, str(sections_path), str(log_path))
        db.set_project_info(project_id, project_info)

        base_name = os.path.splitext(filename)[0]
        bundled = extraction.bundle_outputs_into_zip(sections_bytes, log_bytes, structure_zip, base_name)

        add_step("Preparing the Q&A agent for this document...")
        doc_id = extraction.call_build_index(filename, b64)

        zip_path = config.OUTPUTS_DIR / f"{project_id}.zip"
        with open(zip_path, "wb") as f:
            f.write(bundled)
        db.set_project_output(project_id, str(zip_path), doc_id)
        db.update_project_status(project_id, "extracted")

        scan_path.unlink(missing_ok=True)
        add_step("Done")
        job["status"] = "done"
    except Exception as e:
        if project_id:
            db.update_project_status(project_id, "failed")
        job["status"] = "error"
        job["error"] = f"Extraction failed: {e}"


@router.post("/confirm")
def confirm_and_extract(body: ConfirmProjectRequest, user=Depends(get_current_user)):
    """Step 2: kicks off the full extraction pipeline in a background
    thread and returns immediately with a job_id — the client polls
    GET /confirm/{job_id}/status for live step-by-step progress (see
    _run_confirm_job) instead of blocking on one long request."""
    job_id = str(uuid.uuid4())
    _confirm_jobs[job_id] = {"status": "running", "steps": [], "project_id": None, "error": None}
    thread = threading.Thread(
        target=_run_confirm_job,
        args=(job_id, body.scan_id, body.filename, body.project_info.model_dump(), body.code_corrections, user),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@router.get("/confirm/{job_id}/status")
def get_confirm_status(job_id: str, user=Depends(get_current_user)):
    job = _confirm_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job


@router.get("/{project_id}")
def get_project(project_id: str, user=Depends(get_current_user)):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    role = db.get_project_role(project_id, user["email"])
    return {**project, "my_role": role}


@router.post("/{project_id}/request-access")
def request_access(project_id: str, user=Depends(get_current_user)):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    created = db.request_project_access(project_id, user["email"], user["name"])
    return {"requested": created}


@router.patch("/{project_id}")
def update_project(project_id: str, body: RenamePinRequest, user=Depends(get_current_user)):
    _require_role(project_id, user["email"], {"owner_admin", "admin"})
    if body.title is not None:
        db.rename_project(project_id, body.title.strip() or db.get_project(project_id)["title"])
    if body.pinned is not None:
        db.set_project_pinned(project_id, body.pinned)
    return db.get_project(project_id)


@router.post("/{project_id}/delete-request")
def request_delete(project_id: str, user=Depends(get_current_user)):
    role = _require_role(project_id, user["email"], {"owner_admin", "admin", "assignee"})
    db.request_delete_project(project_id, user["email"])
    if role != "owner_admin":
        owners = [m["user_email"] for m in db.list_project_members(project_id) if m["role"] == "owner_admin"]
        project = db.get_project(project_id)
        for owner in owners:
            db.create_notification(owner, project_id, f"{user['name']} requested to delete {project['title']}")
    return {"ok": True}


@router.post("/{project_id}/delete-cancel")
def cancel_delete(project_id: str, user=Depends(get_current_user)):
    _require_role(project_id, user["email"], {"owner_admin"})
    db.cancel_delete_request(project_id)
    return {"ok": True}


@router.post("/{project_id}/delete-confirm")
def confirm_delete(project_id: str, user=Depends(get_current_user)):
    _require_role(project_id, user["email"], {"owner_admin"})
    project = db.get_project(project_id)
    if project:
        for path_key in ("source_pdf_path", "output_zip_path", "sections_xlsx_path", "log_xlsx_path"):
            path = project.get(path_key)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
    db.delete_project(project_id)
    return {"ok": True}


@router.get("/{project_id}/download")
def download_project_zip(project_id: str, user=Depends(get_current_user)):
    if db.get_project_role(project_id, user["email"]) is None:
        raise HTTPException(403, "You don't have access to this project.")
    project = db.get_project(project_id)
    if not project or not project.get("output_zip_path") or not os.path.exists(project["output_zip_path"]):
        raise HTTPException(404, "No extraction output available yet.")
    filename = f"{os.path.splitext(project['title'])[0]}_submittal_package.zip"
    return FileResponse(project["output_zip_path"], media_type="application/zip", filename=filename)


@router.get("/{project_id}/flags")
def get_flags(project_id: str, user=Depends(get_current_user)):
    if db.get_project_role(project_id, user["email"]) is None:
        raise HTTPException(403, "You don't have access to this project.")
    return db.get_pending_flags(project_id)


@router.post("/{project_id}/flags/{flag_id}/resolve")
def resolve_flag(project_id: str, flag_id: str, body: dict, user=Depends(get_current_user)):
    _require_role(project_id, user["email"], {"owner_admin", "admin"})
    section_id = body.get("section_id")
    resolved_value = (body.get("resolved_value") or "").strip()
    original_code = body.get("original_code")
    if not resolved_value or not section_id:
        raise HTTPException(400, "resolved_value and section_id are required.")
    db.resolve_flag(flag_id, section_id, resolved_value, user["email"])
    if original_code:
        db.sync_section_number(project_id, original_code, resolved_value)
    return {"ok": True}
