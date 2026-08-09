"""
FastAPI dependency that resolves "who is making this request" from the
JWT stored in an httpOnly cookie.

Any route that needs to know the current user declares a parameter like:
    user: User = Depends(get_current_user)
FastAPI calls this function before running the route, and either hands
the route a real, active User object, or short-circuits the request with
a 401 before the route's own code ever runs. This is what makes every
other endpoint in the app automatically per-user: they just filter their
queries by `user.id`.
"""

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db


async def get_current_user(
    # FastAPI automatically reads the "access_token" cookie off the
    # incoming request and passes it in here -- no manual header parsing.
    access_token: str | None = Cookie(default=None),
    # A fresh async DB session for this request, provided by get_db()
    # in app/db/session.py.
    db: AsyncSession = Depends(get_db),
) -> User:
    # Step 1: no cookie at all means the browser never logged in (or the
    # cookie expired/was cleared) -- reject immediately.
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # Step 2: the cookie exists, but is it a valid, unexpired, correctly
    # signed token? decode_access_token returns the user id if so, or
    # None if the token is invalid/expired/tampered with.
    user_id = decode_access_token(access_token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    # Step 3: the token is valid, but does that user id still correspond
    # to a real, active account? (Handles the edge case of an account
    # being deleted/deactivated after the token was issued.)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # All three checks passed -- hand the real User row to the route.
    return user
