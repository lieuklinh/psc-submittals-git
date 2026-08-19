from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..deps import get_current_user
from ..schemas import InviteMemberRequest, UpdateMemberRoleRequest

router = APIRouter(prefix="/api/projects/{project_id}/members", tags=["members"])


def _require_admin(project_id: str, user_email: str):
    role = db.get_project_role(project_id, user_email)
    if role not in ("owner_admin", "admin"):
        raise HTTPException(403, "Only project admins can manage the team.")


def _require_role_grantable(project_id: str, actor_email: str, target_role: str):
    """A plain Admin can manage the rest of the team, but only an existing
    Owner Admin may mint a new one — otherwise any Admin could silently
    self-promote (or promote anyone else) to Owner Admin through invite,
    role-update, or access-approval. Ownership handoff should go through
    an explicit Owner Admin action, not a side effect of team management."""
    if target_role == "owner_admin" and db.get_project_role(project_id, actor_email) != "owner_admin":
        raise HTTPException(403, "Only an Owner Admin can grant the Owner Admin role.")


@router.get("")
def list_members(project_id: str, user=Depends(get_current_user)):
    if db.get_project_role(project_id, user["email"]) is None:
        raise HTTPException(403, "You don't have access to this project.")
    return db.list_project_members(project_id)


@router.post("")
def invite_member(project_id: str, body: InviteMemberRequest, user=Depends(get_current_user)):
    _require_admin(project_id, user["email"])
    _require_role_grantable(project_id, user["email"], body.role)
    email_clean = body.user_email.strip().lower()
    if not email_clean:
        raise HTTPException(400, "user_email is required.")
    project = db.get_project(project_id)
    db.add_project_member(project_id, email_clean, body.role, user["email"])
    db.create_notification(email_clean, project_id, f"{user['name']} added you to {project['title']}")
    return {"ok": True}


@router.patch("/{member_email}")
def update_role(project_id: str, member_email: str, body: UpdateMemberRoleRequest, user=Depends(get_current_user)):
    _require_admin(project_id, user["email"])
    _require_role_grantable(project_id, user["email"], body.role)
    try:
        db.update_member_role(project_id, member_email, body.role, user["email"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/{member_email}/deactivate")
def deactivate_member(project_id: str, member_email: str, user=Depends(get_current_user)):
    _require_admin(project_id, user["email"])
    try:
        db.deactivate_project_member(project_id, member_email, user["email"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.delete("/{member_email}")
def remove_member(project_id: str, member_email: str, user=Depends(get_current_user)):
    _require_admin(project_id, user["email"])
    try:
        db.remove_project_member(project_id, member_email, user["email"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/{member_email}/notify")
def renotify_member(project_id: str, member_email: str, user=Depends(get_current_user)):
    _require_admin(project_id, user["email"])
    project = db.get_project(project_id)
    db.create_notification(member_email, project_id, f"Reminder: you have access to {project['title']}")
    return {"ok": True}


@router.post("/{member_email}/approve")
def approve_access(project_id: str, member_email: str, body: UpdateMemberRoleRequest, user=Depends(get_current_user)):
    _require_admin(project_id, user["email"])
    _require_role_grantable(project_id, user["email"], body.role)
    try:
        db.approve_project_access(project_id, member_email, body.role, user["email"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/{member_email}/deny")
def deny_access(project_id: str, member_email: str, user=Depends(get_current_user)):
    _require_admin(project_id, user["email"])
    db.deny_project_access(project_id, member_email, user["email"])
    return {"ok": True}
