import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from .. import config, db, extraction
from ..deps import get_current_user
from ..schemas import (
    CreateItemRequest, UpdateItemRequest, CommentRequest, MoveItemRequest,
    AssignSectionRequest, SetSectionNotRequiredRequest,
)

router = APIRouter(prefix="/api", tags=["workspace"])


@router.get("/projects/{project_id}/workspace")
def get_workspace(project_id: str, user=Depends(get_current_user)):
    """Everyone who can see this project — Admin, Assignee, Viewer, or a
    non-member hitting the read-only access-request gate — gets the FULL,
    unfiltered workspace. Visibility is universal; only editing is
    restricted, and edit rights are section-scoped (an Assignee can edit
    only sections where specification_sections.assigned_user_email matches
    them, decided client-side using `sections[].assigned_user_email`) per
    the 2026-08 collaborative-workspace spec, section 18. `is_admin` still
    reflects owner_admin/admin for project-wide actions (bulk assign,
    Not Required, +Add, etc). `membership_status` tells the frontend
    whether an access request is pending vs. not yet sent for role=None."""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found.")

    role = db.get_project_role(project_id, user["email"])
    membership_status = db.get_project_membership_status(project_id, user["email"])

    db.migrate_legacy_sections_to_items(project_id, actor_email=user["email"])

    return {
        "role": role,
        "is_admin": role in ("owner_admin", "admin"),
        "membership_status": membership_status,
        "sections": db.get_specification_sections(project_id),
        "items": db.get_submittal_items_for_project(project_id),
        "organizations": db.search_organizations(project_id),
        "members": db.list_project_members(project_id),
    }


@router.post("/projects/{project_id}/sections/{section_id}/items")
def create_item(project_id: str, section_id: str, body: CreateItemRequest, user=Depends(get_current_user)):
    if not db.can_edit_section(section_id, user["email"]):
        raise HTTPException(403, "You can only add submittals to sections assigned to you.")
    item_id = db.create_submittal_item(
        project_id, section_id, body.title, user["email"],
        submittal_type=body.submittal_type, organization_id=body.organization_id,
        responsible_user_email=body.responsible_user_email, due_date=body.due_date, notes=body.notes,
    )
    return {"id": item_id}


@router.post("/projects/{project_id}/sections/{section_id}/summary")
def generate_summary(project_id: str, section_id: str, user=Depends(get_current_user)):
    role = db.get_project_role(project_id, user["email"])
    if role not in ("owner_admin", "admin"):
        raise HTTPException(403, "Only project admins can generate summaries.")
    sections = {s["id"]: s for s in db.get_specification_sections(project_id)}
    section = sections.get(section_id)
    if not section:
        raise HTTPException(404, "Section not found.")
    summary = extraction.generate_section_summary(section, config.OPENAI_API_KEY, config.OPENAI_MODEL)
    if not summary:
        raise HTTPException(422, "Couldn't generate a summary — no OpenAI key configured or no captured text.")
    db.set_section_summary(section_id, summary, model=config.OPENAI_MODEL, version="v1")
    return {"section_summary": summary}


@router.patch("/projects/{project_id}/sections/{section_id}/assign")
def assign_section(project_id: str, section_id: str, body: AssignSectionRequest, user=Depends(get_current_user)):
    role = db.get_project_role(project_id, user["email"])
    if role not in ("owner_admin", "admin"):
        raise HTTPException(403, "Only project admins can assign sections.")
    try:
        db.assign_section(section_id, body.user_email, user["email"])
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.patch("/projects/{project_id}/sections/{section_id}/not-required")
def set_section_not_required(project_id: str, section_id: str, body: SetSectionNotRequiredRequest, user=Depends(get_current_user)):
    role = db.get_project_role(project_id, user["email"])
    if role not in ("owner_admin", "admin"):
        raise HTTPException(403, "Only project admins can mark sections Not Required.")
    try:
        db.set_section_not_required(section_id, body.reason, user["email"], not_required=body.not_required)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.patch("/items/{item_id}")
def update_item(item_id: str, project_id: str, body: UpdateItemRequest, user=Depends(get_current_user)):
    item = db.get_submittal_item(item_id)
    if not item:
        raise HTTPException(404, "Submittal not found.")
    # Full edit rights are section-scoped: Admins can edit any section, an
    # Assignee can edit only sections assigned to them, everyone else
    # (Viewer, or an Assignee on a section that isn't theirs) is read-only
    # — including Status. This is a deliberate change from the old
    # "any assignee can always change Status" rule (2026-08 spec, section
    # 18: "Charles should not be able to... change their statuses" for
    # sections not assigned to him).
    if not db.can_edit_section(item["specification_section_id"], user["email"]):
        raise HTTPException(403, "You can only edit submittals in sections assigned to you.")

    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        db.update_submittal_item(item_id, user["email"], **fields)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/items/{item_id}/duplicate")
def duplicate_item(item_id: str, project_id: str, section_id: str, user=Depends(get_current_user)):
    role = db.get_project_role(project_id, user["email"])
    if role not in ("owner_admin", "admin"):
        raise HTTPException(403, "Only project admins can duplicate submittals.")
    items = {it["id"]: it for it in db.get_submittal_items_for_project(project_id, include_archived=True)}
    original = items.get(item_id)
    if not original:
        raise HTTPException(404, "Submittal not found.")
    new_id = db.create_submittal_item(
        project_id, section_id, f"{original['title']} (copy)", user["email"],
        submittal_type=original["submittal_type"], organization_id=original["organization_id"],
    )
    return {"id": new_id}


@router.post("/items/{item_id}/move")
def move_item(item_id: str, project_id: str, body: MoveItemRequest, user=Depends(get_current_user)):
    role = db.get_project_role(project_id, user["email"])
    if role not in ("owner_admin", "admin"):
        raise HTTPException(403, "Only project admins can reorder submittals.")
    try:
        db.move_submittal_item(item_id, body.direction, user["email"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/items/{item_id}/archive")
def archive_item(item_id: str, project_id: str, user=Depends(get_current_user)):
    role = db.get_project_role(project_id, user["email"])
    if role not in ("owner_admin", "admin"):
        raise HTTPException(403, "Only project admins can archive submittals.")
    db.archive_submittal_item(item_id, user["email"])
    return {"ok": True}


@router.delete("/items/{item_id}")
def delete_item(item_id: str, project_id: str, user=Depends(get_current_user)):
    role = db.get_project_role(project_id, user["email"])
    if role != "owner_admin":
        raise HTTPException(403, "Only the Owner Admin can delete submittals.")
    db.delete_submittal_item(item_id, user["email"])
    return {"ok": True}


@router.get("/items/{item_id}/attachments")
def list_attachments(item_id: str, project_id: str, user=Depends(get_current_user)):
    if db.get_project_role(project_id, user["email"]) is None:
        raise HTTPException(403, "You don't have access to this project.")
    return db.list_attachments(item_id)


@router.post("/items/{item_id}/attachments")
async def upload_attachment(
    item_id: str, project_id: str, file: UploadFile = File(...),
    description: str = Form(...), folder: str = Form("from_vendor"),
    user=Depends(get_current_user),
):
    role = db.get_project_role(project_id, user["email"])
    if role is None:
        raise HTTPException(403, "You don't have access to this project.")
    if role == "viewer":
        raise HTTPException(403, "Viewers have read-only access to this project.")
    if not description.strip():
        raise HTTPException(400, "A brief description is required for every attachment.")
    att_dir = config.ATTACHMENTS_DIR / item_id
    att_dir.mkdir(parents=True, exist_ok=True)
    dest_path = att_dir / file.filename
    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)
    try:
        att_id = db.create_attachment(
            item_id, project_id, str(dest_path), file.filename, user["email"],
            description.strip(), folder=folder,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": att_id}


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: str, user=Depends(get_current_user)):
    att = db.get_attachment(attachment_id)
    if not att or db.get_project_role(att["project_id"], user["email"]) is None:
        raise HTTPException(404, "Attachment not found.")
    if not os.path.exists(att["file_path"]):
        raise HTTPException(404, "File missing on disk.")
    return FileResponse(att["file_path"], filename=att["original_filename"])


@router.get("/items/{item_id}/comments")
def list_comments(item_id: str, project_id: str, user=Depends(get_current_user)):
    if db.get_project_role(project_id, user["email"]) is None:
        raise HTTPException(403, "You don't have access to this project.")
    return db.list_comments(item_id)


@router.post("/items/{item_id}/comments")
def add_comment(item_id: str, project_id: str, body: CommentRequest, user=Depends(get_current_user)):
    role = db.get_project_role(project_id, user["email"])
    if role is None:
        raise HTTPException(403, "You don't have access to this project.")
    if role == "viewer":
        raise HTTPException(403, "Viewers have read-only access to this project.")
    if not body.body.strip():
        raise HTTPException(400, "Comment body is required.")
    comment_id = db.create_comment(item_id, project_id, user["email"], body.body.strip())
    return {"id": comment_id}


@router.get("/items/{item_id}/activity")
def item_activity(item_id: str, project_id: str, user=Depends(get_current_user)):
    if db.get_project_role(project_id, user["email"]) is None:
        raise HTTPException(403, "You don't have access to this project.")
    return db.get_activity_for_item(item_id)


@router.get("/projects/{project_id}/activity")
def project_activity(project_id: str, user=Depends(get_current_user)):
    role = db.get_project_role(project_id, user["email"])
    if role not in ("owner_admin", "admin"):
        raise HTTPException(403, "Only project admins can view the activity history.")
    return db.get_activity_for_project(project_id)
