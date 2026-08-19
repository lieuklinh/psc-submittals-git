from fastapi import APIRouter, Depends, HTTPException

from .. import db, extraction
from ..deps import get_current_user
from ..schemas import ChatRequest

router = APIRouter(prefix="/api/projects/{project_id}/chat", tags=["qna"])


@router.post("")
def chat(project_id: str, body: ChatRequest, user=Depends(get_current_user)):
    if db.get_project_role(project_id, user["email"]) is None:
        raise HTTPException(403, "You don't have access to this project.")
    if not body.message.strip():
        raise HTTPException(400, "message is required.")
    project = db.get_project(project_id)
    answer = extraction.call_agent_chat(body.message.strip(), project.get("qna_doc_id"))
    return {"answer": answer}
