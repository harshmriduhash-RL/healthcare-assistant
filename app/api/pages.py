"""
Page routes: HTML pages served via Jinja2 templates.
"""

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.security import decode_access_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def root(request: Request, access_token: str | None = Cookie(default=None)):
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
    if not access_token or not decode_access_token(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, access_token: str | None = Cookie(default=None)):
    if not access_token or not decode_access_token(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("chat.html", {"request": request})


@router.get("/timeline", response_class=HTMLResponse)
async def timeline_page(request: Request, access_token: str | None = Cookie(default=None)):
    if not access_token or not decode_access_token(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("timeline.html", {"request": request})


@router.get("/report", response_class=HTMLResponse)
async def report_page(request: Request, access_token: str | None = Cookie(default=None)):
    if not access_token or not decode_access_token(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("report.html", {"request": request})


@router.get("/patient/touchpoint/{share_token}", response_class=HTMLResponse)
async def public_patient_touchpoint(request: Request, share_token: str):
    """Simplified, large-font web touchpoint view for patients (zero login needed)."""
    return templates.TemplateResponse("patient_checkin.html", {"request": request, "share_token": share_token})


@router.get("/emergency", response_class=HTMLResponse)
async def emergency_page(request: Request, access_token: str | None = Cookie(default=None)):
    """One-Tap Emergency SOS screen."""
    if not access_token or not decode_access_token(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("emergency.html", {"request": request})
