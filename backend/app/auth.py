"""Authentication: username/password + per-user server-side sessions.

Central, multi-tenant-independent: one `data/auth.db` for the whole app (NOT the
per-store/project pipeline DBs). Designed to scale to 1000+ users — users and
sessions are indexed rows, password hashing is stdlib PBKDF2 (no native dep), and
the only state is a session token, so it swaps to Postgres by changing the URL.

Security model:
  * passwords stored as `pbkdf2_sha256$iters$salt$hash` (per-user random salt);
  * a login mints a random opaque token stored server-side with an expiry;
  * **one active session per user** — a new login revokes the user's old sessions;
  * the SPA sends the token as `Authorization: Bearer <token>`; expired/unknown
    tokens 401.
"""
from __future__ import annotations
import os
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import (create_engine, event, Column, Integer, String, Boolean, DateTime,
                        select, delete)
from sqlalchemy.orm import declarative_base, sessionmaker

# ---- storage ----------------------------------------------------------------
# computed locally (not imported from database) to avoid an import cycle:
# database.get_db depends on auth.current_user for per-user data scoping.
_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
_AUTH_DB = os.path.join(_DATA_DIR, "auth.db")
_engine = create_engine(f"sqlite:///{_AUTH_DB}", future=True,
                        connect_args={"check_same_thread": False, "timeout": 30})
# WAL + busy timeout: every request touches sessions (sliding expiry), so the
# auth db sees constant tiny writes — rollback-journal mode would let them
# collide with concurrent request reads as "database is locked" 500s.


@event.listens_for(_engine, "connect")
def _auth_on_connect(conn, _rec):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")


SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
Base = declarative_base()

SESSION_TTL = timedelta(hours=int(os.getenv("AUTH_SESSION_HOURS", "12")))
_PBKDF2_ITERS = 240_000
_SUPERUSER = (os.getenv("SUPERUSER_NAME", "SAdmin"), os.getenv("SUPERUSER_PASS", "RootPass"))


class User(Base):
    __tablename__ = "users"
    # sqlite_autoincrement: ids are NEVER reused after delete, so a new user can't
    # inherit a deleted user's store directory (which is namespaced by user id).
    __table_args__ = {"sqlite_autoincrement": True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuthSession(Base):
    __tablename__ = "sessions"
    token = Column(String, primary_key=True)
    username = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)


# ---- password hashing (stdlib PBKDF2) ---------------------------------------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, iters, salt_b64, hash_b64 = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt_b64), int(iters))
        return secrets.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)   # SQLite drops tzinfo


# ---- bootstrap --------------------------------------------------------------
def init_auth() -> None:
    """Create tables + seed the superuser. Idempotent (safe every startup)."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    Base.metadata.create_all(_engine)
    name, pw = _SUPERUSER
    with SessionLocal() as s:
        if not s.scalar(select(User).where(User.username == name)):
            s.add(User(username=name, password_hash=hash_password(pw), is_superuser=True))
            s.commit()


# ---- user management --------------------------------------------------------
def create_user(username: str, password: str, is_superuser: bool = False) -> User:
    username = (username or "").strip()
    if not username or not password:
        raise ValueError("username and password required")
    with SessionLocal() as s:
        if s.scalar(select(User).where(User.username == username)):
            raise ValueError(f"user '{username}' already exists")
        u = User(username=username, password_hash=hash_password(password), is_superuser=is_superuser)
        s.add(u); s.commit(); s.refresh(u)
        return u


def list_users() -> list[dict]:
    with SessionLocal() as s:
        return [{"id": u.id, "username": u.username, "is_superuser": u.is_superuser,
                 "is_active": u.is_active,
                 "created_at": _aware(u.created_at).isoformat() if u.created_at else None}
                for u in s.scalars(select(User).order_by(User.username)).all()]


def _purge_user_stores(user_id: int) -> None:
    """Remove the user's store directories (data is namespaced `u<id>__*`)."""
    import shutil
    stores_dir = os.path.join(_DATA_DIR, "stores")
    pre = f"u{user_id}__"
    if os.path.isdir(stores_dir):
        for d in os.listdir(stores_dir):
            if d.startswith(pre):
                shutil.rmtree(os.path.join(stores_dir, d), ignore_errors=True)


def delete_user(username: str) -> None:
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.username == username))
        if not u:
            raise ValueError("user not found")
        if u.is_superuser:
            raise ValueError("cannot delete a superuser")
        uid = u.id
        s.execute(delete(AuthSession).where(AuthSession.username == username))
        s.delete(u); s.commit()
    _purge_user_stores(uid)   # delete their isolated data too


def set_password(username: str, password: str, revoke_sessions: bool = True) -> None:
    if not password:
        raise ValueError("password required")
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.username == username))
        if not u:
            raise ValueError("user not found")
        u.password_hash = hash_password(password)
        if revoke_sessions:
            s.execute(delete(AuthSession).where(AuthSession.username == username))
        s.commit()


# ---- login / sessions -------------------------------------------------------
def authenticate(username: str, password: str) -> User | None:
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.username == username))
        if u and u.is_active and verify_password(password, u.password_hash):
            return u
        return None


def login(username: str, password: str) -> str | None:
    """Verify creds, revoke the user's existing sessions (one active per user),
    mint + store a new token. Returns the token, or None on bad creds."""
    u = authenticate(username, password)
    if not u:
        return None
    token = secrets.token_urlsafe(32)
    now = _now()
    with SessionLocal() as s:
        s.execute(delete(AuthSession).where(AuthSession.username == u.username))  # unique session
        s.add(AuthSession(token=token, username=u.username,
                          created_at=now, expires_at=now + SESSION_TTL, last_seen=now))
        s.commit()
    return token


def logout(token: str) -> None:
    with SessionLocal() as s:
        s.execute(delete(AuthSession).where(AuthSession.token == token)); s.commit()


def resolve(token: str) -> User | None:
    """Validate a token -> the user; slides the expiry forward. None if invalid."""
    if not token:
        return None
    now = _now()
    with SessionLocal() as s:
        sess = s.get(AuthSession, token)
        if not sess:
            return None
        if _aware(sess.expires_at) < now:
            s.delete(sess); s.commit()
            return None
        sess.last_seen = now
        sess.expires_at = now + SESSION_TTL       # sliding window
        u = s.scalar(select(User).where(User.username == sess.username))
        if not u or not u.is_active:
            s.delete(sess); s.commit()
            return None
        s.commit()
        return u


# ---- FastAPI dependencies ---------------------------------------------------
_bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    user = resolve(creds.credentials) if creds else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require_superuser(user: User = Depends(current_user)) -> User:
    if not user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superuser only")
    return user
