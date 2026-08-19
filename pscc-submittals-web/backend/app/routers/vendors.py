from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..deps import get_current_user
from ..schemas import CreateOrganizationRequest, UpdateOrganizationRequest

router = APIRouter(prefix="/api/projects/{project_id}/organizations", tags=["vendors"])


def _require_admin(project_id: str, user_email: str):
    role = db.get_project_role(project_id, user_email)
    if role not in ("owner_admin", "admin"):
        raise HTTPException(403, "Only project admins can manage vendors.")


@router.get("")
def list_organizations(project_id: str, user=Depends(get_current_user)):
    if db.get_project_role(project_id, user["email"]) is None:
        raise HTTPException(403, "You don't have access to this project.")
    return db.list_all_organizations(project_id)


@router.post("")
def create_organization(project_id: str, body: CreateOrganizationRequest, user=Depends(get_current_user)):
    role = db.get_project_role(project_id, user["email"])
    if role is None:
        raise HTTPException(403, "You don't have access to this project.")
    if role == "viewer":
        raise HTTPException(403, "Viewers have read-only access to this project.")
    if not body.organization_name.strip():
        raise HTTPException(400, "organization_name is required.")
    try:
        org_id, was_created = db.create_organization(
            project_id, body.organization_name.strip(), body.organization_type,
            contact_name=body.primary_contact_name, email=body.email, phone=body.phone, trade=body.trade,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": org_id, "created": was_created}


@router.patch("/{org_id}")
def update_organization(project_id: str, org_id: str, body: UpdateOrganizationRequest, user=Depends(get_current_user)):
    _require_admin(project_id, user["email"])
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    db.update_organization(org_id, **fields)
    return {"ok": True}


@router.post("/{org_id}/deactivate")
def deactivate_organization(project_id: str, org_id: str, user=Depends(get_current_user)):
    _require_admin(project_id, user["email"])
    db.deactivate_organization(org_id)
    return {"ok": True}


@router.post("/{org_id}/reactivate")
def reactivate_organization(project_id: str, org_id: str, user=Depends(get_current_user)):
    _require_admin(project_id, user["email"])
    db.reactivate_organization(org_id)
    return {"ok": True}
