from fastapi import APIRouter, Depends

from .. import db
from ..deps import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(user=Depends(get_current_user)):
    return db.get_notifications(user["email"])


@router.post("/{notification_id}/read")
def mark_read(notification_id: str, user=Depends(get_current_user)):
    db.mark_notification_read(notification_id)
    return {"ok": True}
