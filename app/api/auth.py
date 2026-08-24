"""
Authentication routes: signup, login, logout.

Deliberately minimal by product decision: username + password only, no
email verification, no OTP, no third-party auth (Google, etc). Simpler
signup/login at the cost of no email-based "forgot password" recovery
flow -- an acceptable tradeoff for this prototype.

All three routes issue/clear the SAME httpOnly cookie ("access_token"),
which is what app/core/deps.py's get_current_user reads on every
protected request. httpOnly means client-side JavaScript can't read this
cookie (mitigating XSS-based token theft); it's sent automatically by the
browser on every request to this origin.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.schemas import LoginRequest, SignupRequest
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup")
async def signup(payload: SignupRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Create a new account. Rejects duplicate usernames, hashes the
    password before storing it, and immediately logs the new user in by
    setting the auth cookie -- no separate login step required right
    after signing up.
    """
    existing = await db.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(username=payload.username, hashed_password=hash_password(payload.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)  # load DB-generated fields (id, created_at) before we use user.id below

    token = create_access_token(subject=user.id)
    # samesite="lax" allows the cookie on normal top-level navigation
    # (e.g. following a link) while still blocking it on most
    # cross-site POST requests -- a reasonable CSRF-mitigation default
    # for this kind of app. max_age is in seconds (24 hours here).
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24)
    return {"id": user.id, "username": user.username}


@router.post("/login")
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Verify credentials and set the auth cookie on success.

    Deliberately returns the SAME error message ("Invalid username or
    password") whether the username doesn't exist or the password is
    wrong -- this avoids leaking which usernames are registered to an
    attacker probing the login endpoint.
    """
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_access_token(subject=user.id)
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24)
    return {"id": user.id, "username": user.username}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return {"id": user.id, "username": user.username}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/", httponly=True, samesite="lax")
    response.delete_cookie("active_patient_id", path="/")
    return {"ok": True}

