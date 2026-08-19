import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"
ATTACHMENTS_DIR = DATA_DIR / "attachments"
SCANS_DIR = DATA_DIR / "scans"  # temp holding area between /scan and /confirm

for _d in (DATA_DIR, UPLOADS_DIR, OUTPUTS_DIR, ATTACHMENTS_DIR, SCANS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/pscc_submittals",
)
EXTRACTION_BACKEND_URL = os.getenv("EXTRACTION_BACKEND_URL", "http://localhost:8000").rstrip("/")
AGENT_URL = os.getenv("AGENT_URL", "http://localhost:8100").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
TEAM_LEAD_EMAILS = {
    e.strip().lower() for e in os.getenv("TEAM_LEAD_EMAILS", "charles@pscc.com").split(",") if e.strip()
}
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
