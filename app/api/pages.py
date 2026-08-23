"""
Page routes: serve the actual HTML pages (via Jinja2 templates) rather
than JSON. Everything under app/templates/ is rendered from here.

Each protected page (dashboard, chat) does its own lightweight auth
check directly against the cookie -- reading and decoding the JWT right
here, rather than using the get_current_user dependency (app/core/deps.py)
-- because a failed auth check on a PAGE route should redirect the
browser to /login (a 302), not return a 401 JSON error like the API
routes do. The actual API calls those pages make (e.g. /api/dashboard/medicines)
DO use get_current_user and its 401 behavior, since those are called by
JavaScript, not navigated to directly.
"""

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.security import decode_access_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def root(request: Request, access_token: str | None = Cookie(default=None)):
    """Landing route: serve the landing page with product information.
    If already logged in, the landing page will show a "Go to Dashboard" button.
    """
    is_logged_in = bool(access_token and decode_access_token(access_token))
    return templates.TemplateResponse("landing.html", {"request": request, "is_logged_in": is_logged_in})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, access_token: str | None = Cookie(default=None)):
    """The main dashboard: medicines, dosages, appointments, records,
    and reminders. See app/templates/dashboard.html for the page itself
    and its JavaScript, which calls the /api/dashboard/*, /api/records/*,
    and /api/notifications/* routes to populate everything.
    """
    if not access_token or not decode_access_token(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, access_token: str | None = Cookie(default=None)):
    """The AI assistant chat page -- where the multi-agent + HITL system
    actually runs. See app/templates/chat.html for the approval-card UI
    and its calls to /api/chat/start and /api/chat/resume.
    """
    if not access_token or not decode_access_token(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("chat.html", {"request": request})


@router.get("/timeline", response_class=HTMLResponse)
async def timeline_page(request: Request, access_token: str | None = Cookie(default=None)):
    """The unified health timeline page (Phase 2 feature)."""
    if not access_token or not decode_access_token(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("timeline.html", {"request": request})
@router.get("/report", response_class=HTMLResponse)
async def report_page(request: Request, access_token: str | None = Cookie(default=None)):
    """Weekly adherence report (printable)."""
    if not access_token or not decode_access_token(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("report.html", {"request": request})


@router.get("/caregiver/{username}", response_class=HTMLResponse)
async def caregiver_page(request: Request, username: str):
    """Public read-only timeline for caregivers/family."""
    return templates.TemplateResponse("caregiver.html", {"request": request, "patient_username": username})
