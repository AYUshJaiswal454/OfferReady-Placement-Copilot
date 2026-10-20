from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator
from starlette.responses import JSONResponse

from ..config import get_settings
from ..db import audit, get_db, now_iso
from ..security import failed_logins, SESSION_COOKIE, create_session_token, hash_password, verify_password
from ..web import ApiError, Ctx, Router, public_user

router = Router("/api")
CONSENT_VERSION = "2026-10-v1"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=120)
    password: str = Field(min_length=8, max_length=128)
    roll_no: str | None = Field(default=None, max_length=40)
    batch_year: int | None = Field(default=None, ge=2000, le=2100)
    branch: str | None = Field(default=None, max_length=60)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v


class LoginIn(BaseModel):
    email: str
    password: str


class MeIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    roll_no: str | None = Field(default=None, max_length=40)
    batch_year: int | None = Field(default=None, ge=2000, le=2100)
    branch: str | None = Field(default=None, max_length=60)
    target_role: str | None = Field(default=None, max_length=80)
    job_type: str | None = Field(default=None, pattern="^(internship|fulltime|both)$")
    target_locations: list[str] | None = Field(default=None, max_length=10)


def _session_response(user: dict) -> JSONResponse:
    token = create_session_token(int(user["id"]), user["role"])
    resp = JSONResponse({"user": public_user(user), "token": token})
    resp.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax", secure=get_settings().base_url.startswith("https"),
        max_age=get_settings().session_days * 86400, path="/",
    )
    return resp


@router.post("/auth/signup", auth="public", rate=(300, 3600))   # per IP: a whole lab may sign up from one campus NAT
def signup(ctx: Ctx):
    data = ctx.parse(SignupIn)
    db = get_db()
    if db.fetchone("SELECT id FROM users WHERE email = ?", (data.email,)):
        raise ApiError(409, "An account with this email already exists", "email_taken")
    uid = db.insert("users", {
        "email": data.email,
        "password_hash": hash_password(data.password),
        "name": data.name.strip(),
        "role": "student",
        "roll_no": data.roll_no,
        "batch_year": data.batch_year,
        "branch": data.branch,
        "created_at": now_iso(),
        "target_locations": [],
        "settings": {},
    })
    audit(uid, "signup", "user", uid)
    return _session_response(db.fetchone("SELECT * FROM users WHERE id = ?", (uid,)))


@router.post("/auth/login", auth="public", rate=(600, 300))    # per IP (campus NAT); brute force is limited per account below
def login(ctx: Ctx):
    data = ctx.parse(LoginIn)
    email = data.email.strip().lower()
    if failed_logins.count(email, 900) >= 10:
        raise ApiError(429, "Too many failed sign-in attempts for this account. Wait 15 minutes or reset your password "
                            "with the placement cell.", "rate_limited")
    user = get_db().fetchone("SELECT * FROM users WHERE email = ?", (email,))
    if not user or not verify_password(data.password, user["password_hash"]):
        failed_logins.hit(email)
        raise ApiError(401, "Wrong email or password", "bad_credentials")
    return _session_response(user)


@router.post("/auth/logout", auth="public")
def logout(ctx: Ctx):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/auth/me", auth="public")
def me(ctx: Ctx):
    # Public so the app can ask "am I signed in?" without logging a 401 in the browser console.
    return {"user": public_user(ctx.user) if ctx.user else None, "consent_version": CONSENT_VERSION}


@router.post("/me/consent")
def consent(ctx: Ctx):
    body = ctx.body or {}
    if not body.get("accept"):
        raise ApiError(400, "Consent must be accepted to continue", "consent")
    get_db().update("users", ctx.uid, {"consent_at": now_iso(), "consent_version": CONSENT_VERSION})
    audit(ctx.uid, "consent.accept", "user", ctx.uid, {"version": CONSENT_VERSION})
    return {"user": public_user(get_db().fetchone("SELECT * FROM users WHERE id = ?", (ctx.uid,)))}


@router.patch("/me")
def update_me(ctx: Ctx):
    data = ctx.parse(MeIn).model_dump(exclude_none=True)
    if "target_locations" in data:
        data["target_locations"] = [s.strip()[:60] for s in data["target_locations"] if s.strip()]
    get_db().update("users", ctx.uid, data)
    user = get_db().fetchone("SELECT * FROM users WHERE id = ?", (ctx.uid,))
    return {"user": public_user(user)}
