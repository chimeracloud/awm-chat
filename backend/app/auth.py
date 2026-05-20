"""Firebase ID token verification middleware."""
from typing import Annotated

import firebase_admin
from firebase_admin import auth as fb_auth, credentials
from fastapi import Depends, Header, HTTPException, status

from .config import get_settings

# Initialise once. On Cloud Run the default service account is used.
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(credentials.ApplicationDefault())


class AuthedUser:
    def __init__(self, uid: str, email: str, name: str | None, picture: str | None):
        self.uid = uid
        self.email = email
        self.name = name
        self.picture = picture


async def require_user(
    authorization: Annotated[str | None, Header()] = None,
) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    token = authorization.removeprefix("Bearer ").strip()
    settings = get_settings()
    try:
        decoded = fb_auth.verify_id_token(token)
    except Exception as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")

    email = (decoded.get("email") or "").lower()
    if not email.endswith(f"@{settings.ALLOWED_EMAIL_DOMAIN}"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Domain not permitted")
    if not decoded.get("email_verified", False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Email not verified")

    return AuthedUser(
        uid=decoded["uid"],
        email=email,
        name=decoded.get("name"),
        picture=decoded.get("picture"),
    )


async def require_admin(user: Annotated[AuthedUser, Depends(require_user)]) -> AuthedUser:
    from .storage import db
    snap = db().collection("users").document(user.uid).get()
    if not snap.exists or snap.to_dict().get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user
