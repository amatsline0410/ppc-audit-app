"""Auth endpoints: login / logout / me + superuser-only user management."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from .. import auth

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


class LoginBody(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    password: str
    is_superuser: bool = False


class PasswordBody(BaseModel):
    password: str


def _me(u: auth.User) -> dict:
    return {"username": u.username, "is_superuser": u.is_superuser}


@router.post("/register")
def register(body: LoginBody):
    """Public self-signup: create a normal account, then sign in. No email/OTP."""
    if len(body.password) < 6:
        raise HTTPException(400, "password must be at least 6 characters")
    try:
        auth.create_user(body.username, body.password, is_superuser=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    token = auth.login(body.username, body.password)
    return {"token": token, "user": _me(auth.authenticate(body.username, body.password))}


@router.post("/login")
def login(body: LoginBody):
    token = auth.login(body.username, body.password)
    if not token:
        raise HTTPException(401, "invalid username or password")
    user = auth.authenticate(body.username, body.password)
    return {"token": token, "user": _me(user)}


@router.post("/logout")
def logout(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    if creds:
        auth.logout(creds.credentials)
    return {"ok": True}


@router.get("/me")
def me(user: auth.User = Depends(auth.current_user)):
    return _me(user)


# ---- user management (superuser only) ---------------------------------------
@router.get("/users")
def list_users(_: auth.User = Depends(auth.require_superuser)):
    return {"users": auth.list_users()}


@router.post("/users")
def create_user(body: UserCreate, _: auth.User = Depends(auth.require_superuser)):
    try:
        u = auth.create_user(body.username, body.password, body.is_superuser)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"username": u.username, "is_superuser": u.is_superuser}


@router.delete("/users/{username}")
def delete_user(username: str, _: auth.User = Depends(auth.require_superuser)):
    try:
        auth.delete_user(username)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.patch("/users/{username}/password")
def set_password(username: str, body: PasswordBody, _: auth.User = Depends(auth.require_superuser)):
    try:
        auth.set_password(username, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}
