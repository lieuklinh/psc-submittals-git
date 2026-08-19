from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, db
from .routers import projects, workspace, vendors, members, notifications, qna, directory

app = FastAPI(title="PSCC Submittal Extractor — Web API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    db.init_db()


@app.get("/health")
def health():
    return {"status": "healthy"}


app.include_router(projects.router)
app.include_router(workspace.router)
app.include_router(vendors.router)
app.include_router(members.router)
app.include_router(notifications.router)
app.include_router(qna.router)
app.include_router(directory.router)
