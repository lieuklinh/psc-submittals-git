from typing import Optional

from pydantic import BaseModel


class ProjectInfo(BaseModel):
    project_name: str = ""
    ccua_project_number: str = ""
    pscc_job_number: str = ""
    engineer_name: str = ""
    engineer_address: str = ""
    contractor_name: str = ""
    contractor_address: str = ""
    owner_name: str = ""
    owner_address: str = ""
    prepared_by: str = ""


class ConfirmProjectRequest(BaseModel):
    scan_id: str
    filename: str
    project_info: ProjectInfo
    code_corrections: dict[str, str] = {}


class RenamePinRequest(BaseModel):
    title: Optional[str] = None
    pinned: Optional[bool] = None


class ResolveFlagRequest(BaseModel):
    resolved_value: str


class CreateItemRequest(BaseModel):
    title: str
    submittal_type: Optional[str] = None
    organization_id: Optional[str] = None
    responsible_user_email: Optional[str] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None


class UpdateItemRequest(BaseModel):
    title: Optional[str] = None
    submittal_type: Optional[str] = None
    submittal_type_other: Optional[str] = None
    organization_id: Optional[str] = None
    responsible_user_email: Optional[str] = None
    status: Optional[str] = None
    status_reason: Optional[str] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None
    revision_letter: Optional[str] = None


class MoveItemRequest(BaseModel):
    direction: str


class CreateOrganizationRequest(BaseModel):
    organization_name: str
    organization_type: str = "subcontractor"
    primary_contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    trade: Optional[str] = None


class UpdateOrganizationRequest(BaseModel):
    organization_name: Optional[str] = None
    organization_type: Optional[str] = None
    primary_contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    trade: Optional[str] = None


class InviteMemberRequest(BaseModel):
    user_email: str
    role: str = "assignee"


class UpdateMemberRoleRequest(BaseModel):
    role: str


class CommentRequest(BaseModel):
    body: str


class AssignSectionRequest(BaseModel):
    user_email: Optional[str] = None


class SetSectionNotRequiredRequest(BaseModel):
    reason: Optional[str] = None
    not_required: bool = True


class ChatRequest(BaseModel):
    message: str
