"""
The FastAPI application entry point for CarePilot AI.

Mounts static files, registers API routers (auth, chat, patients, checkin, alerts,
records, dashboard, notifications, family, india_services, emergency, pages),
and manages the background scheduler lifecycle.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import (
    alerts,
    auth,
    chat,
    checkin,
    dashboard,
    emergency,
    family,
    india_services,
    notifications,
    pages,
    patients,
    records,
    timeline,
)
from app.core.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="CarePilot AI — Caregiving Intelligence System", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register all API & Page routers
app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(checkin.router)
app.include_router(alerts.router)
app.include_router(chat.router)
app.include_router(records.router)
app.include_router(dashboard.router)
app.include_router(notifications.router)
app.include_router(family.router)
app.include_router(india_services.router)
app.include_router(emergency.router)
app.include_router(timeline.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "CarePilot AI"}
