from fastapi import APIRouter, Depends

from .. import db
from ..deps import get_current_user

router = APIRouter(prefix="/api/directory", tags=["directory"])


@router.get("/search")
def search_directory(q: str = "", user=Depends(get_current_user)):
    """Operations Team Directory typeahead — any signed-in user can search;
    it's just a lookup, not a project-scoped action."""
    if not q.strip():
        return []
    return db.search_directory(q.strip())
