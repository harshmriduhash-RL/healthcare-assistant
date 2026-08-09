"""
Password hashing and JWT (JSON Web Token) helpers.

This is the ONLY file that touches password hashing or token
encoding/decoding directly -- app/api/auth.py and app/core/deps.py both
call into these functions rather than using `jwt`/`passlib` themselves,
so if we ever need to change the hashing algorithm or token format, it
only has to change here.
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
import bcrypt

from app.core.config import settings

# Direct bcrypt hashing avoids the passlib/bcrypt compatibility issue in
# this environment. The application still stores only salted hashes.
BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """Turn a plaintext password into a salted bcrypt hash for storage.

    We NEVER store the plaintext password anywhere -- only this hash goes
    into the `users.hashed_password` column.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a login attempt's plaintext password against the stored hash.

    Returns True only if they match. bcrypt hashing is one-way, so this is
    the only way to check a password -- we re-hash the attempt with the
    same salt embedded in `hashed_password` and compare.
    """
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(subject: str) -> str:
    """Create a signed JWT for a logged-in user.

    `subject` is the user's id (a UUID string) -- it becomes the "sub"
    (subject) claim inside the token. The token also carries an "exp"
    (expiry) claim so it automatically stops being valid after
    `settings.jwt_expire_minutes`. The token is signed with
    `settings.jwt_secret_key`, so it can't be forged or tampered with
    without knowing that secret.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode = {"sub": subject, "exp": expire}
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """Verify a JWT's signature and expiry, and return the user id inside it.

    Returns None if the token is invalid, tampered with, or expired --
    callers (see app/core/deps.py) treat a None return as "not authenticated."
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except JWTError:
        # Covers: bad signature, malformed token, and expired tokens --
        # python-jose raises JWTError (or a subclass) for all of these.
        return None
