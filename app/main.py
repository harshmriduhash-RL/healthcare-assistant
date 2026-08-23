"""
The FastAPI application entry point.

Run with:  uvicorn app.main:app --reload

This file's only jobs are: (1) create the FastAPI app, (2) mount static
files and register every router (auth, chat, records, dashboard,
notifications, pages), and (3) start/stop the background scheduler
alongside the app's own lifecycle. All actual route logic lives in the
individual files under app/api/.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth, chat, dashboard, notifications, pages, records, timeline
from app.core.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI's lifespan context manager: code before `yield` runs once
    on startup, code after `yield` runs once on shutdown. This is where
    the background reminder scheduler (app/core/scheduler.py) is started
    and stopped, so it runs for exactly as long as the app itself does.
    """
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="CarePilot — Multi-Agent Healthcare Assistant", lifespan=lifespan)

# Serves everything under app/static/ (currently just the shared
# stylesheet) at the URL prefix /static -- referenced from base.html as
# e.g. <link rel="stylesheet" href="/static/css/style.css">.
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Each router owns its own URL prefix (see the `prefix=` argument inside
# each router file) -- registering them here is what actually wires them
# into the running app.
app.include_router(pages.router)          # HTML pages: /, /login, /signup, /dashboard, /chat
app.include_router(auth.router)           # /api/auth/*
app.include_router(chat.router)           # /api/chat/*  -- the agent/HITL system
app.include_router(records.router)        # /api/records/*
app.include_router(dashboard.router)      # /api/dashboard/*  -- direct CRUD
app.include_router(notifications.router)  # /api/notifications/*
app.include_router(timeline.router)       # /api/timeline/*


@app.get("/api/health")
async def health():
    """Simple liveness check -- useful for confirming the server is up
    without needing auth or hitting the database.
    """
    return {"status": "ok"}
