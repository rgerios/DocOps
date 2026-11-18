from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import audit, current_user
from ..models import Membership, Tenant, User
from ..security import (COOKIE, hash_password, make_session, new_totp_secret, password_problems, totp_ok, totp_qr_svg,
                        verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_DUMMY = hash_password("docops-timing-dummy")


class LoginIn(BaseModel):
    email: str
    password: str
    totp: str | None = None


def user_out(db: Session, u: User) -> dict:
    if u.is_superadmin:
        tenants = [{"id": t.id, "name": t.name, "slug": t.slug, "color": t.color, "role": "admin"}
                   for t in db.scalars(select(Tenant).order_by(Tenant.name))]
    else:
        tenants = [{"id": m.tenant.id, "name": m.tenant.name, "slug": m.tenant.slug, "color": m.tenant.color, "role": m.role}
                   for m in db.scalars(select(Membership).where(Membership.user_id == u.id))]
        tenants.sort(key=lambda x: x["name"].lower())
    return {"id": u.id, "email": u.email, "name": u.name, "is_superadmin": u.is_superadmin,
            "must_change_password": u.must_change_password, "totp_enabled": u.totp_enabled,
            "last_login": u.last_login, "tenants": tenants, "app_name": settings.app_name}


def set_cookie(resp: Response, u: User):
    resp.set_cookie(COOKIE, make_session(u.id, u.session_version), httponly=True, secure=settings.cookie_secure,
                    samesite="strict", max_age=settings.session_hours * 3600, path="/")


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    u = db.scalar(select(User).where(func.lower(User.email) == email))
    now = datetime.now(timezone.utc)
    generic = HTTPException(401, "E-mail ou senha inválidos.")
    if not u or not u.active:
        verify_password(_DUMMY, body.password)  # tempo constante para e-mail inexistente
        raise generic
    locked = u.locked_until and (u.locked_until.replace(tzinfo=timezone.utc) if u.locked_until.tzinfo is None else u.locked_until) > now
    if locked:
        raise HTTPException(423, "Conta bloqueada temporariamente por tentativas inválidas. Tente mais tarde.")
    if not verify_password(u.password_hash, body.password):
        u.failed_attempts += 1
        if u.failed_attempts >= settings.max_failed_logins:
            u.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            u.failed_attempts = 0
            db.commit()
            audit(db, request, u, "login.locked")
            raise HTTPException(423, f"Conta bloqueada por {settings.lockout_minutes} minutos após tentativas inválidas.")
        db.commit()
        audit(db, request, u, "login.failed")
        raise generic
    if u.totp_enabled:
        if not body.totp:
            raise HTTPException(401, detail={"mfa_required": True, "message": "Informe o código do autenticador."})
        if not totp_ok(u.totp_secret, body.totp):
            u.failed_attempts += 1
            db.commit()
            raise HTTPException(401, detail={"mfa_required": True, "message": "Código MFA inválido."})
    u.failed_attempts = 0
    u.locked_until = None
    u.last_login = now
    db.commit()
    set_cookie(response, u)
    audit(db, request, u, "login.ok")
    return user_out(db, u)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, response: Response, u: User = Depends(current_user), db: Session = Depends(get_db)):
    u.session_version += 1
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    audit(db, request, u, "logout.all")
    return {"ok": True}


@router.get("/me")
def me(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, u)


class PasswordIn(BaseModel):
    current: str
    new: str


@router.post("/password")
def change_password(body: PasswordIn, request: Request, response: Response, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(u.password_hash, body.current):
        raise HTTPException(400, "Senha atual incorreta.")
    probs = password_problems(body.new)
    if probs:
        raise HTTPException(400, "A nova senha precisa ter: " + ", ".join(probs) + ".")
    if verify_password(u.password_hash, body.new):
        raise HTTPException(400, "A nova senha precisa ser diferente da atual.")
    u.password_hash = hash_password(body.new)
    u.must_change_password = False
    u.session_version += 1
    db.commit()
    set_cookie(response, u)
    audit(db, request, u, "password.changed")
    return user_out(db, u)


@router.post("/mfa/setup")
def mfa_setup(u: User = Depends(current_user), db: Session = Depends(get_db)):
    if u.totp_enabled:
        raise HTTPException(400, "MFA já está ativo. Desative antes de configurar outro autenticador.")
    u.totp_secret = new_totp_secret()
    db.commit()
    uri, qr = totp_qr_svg(u.totp_secret, u.email)
    return {"secret": u.totp_secret, "uri": uri, "qr": qr}


class CodeIn(BaseModel):
    code: str


@router.post("/mfa/enable")
def mfa_enable(body: CodeIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not u.totp_secret or not totp_ok(u.totp_secret, body.code):
        raise HTTPException(400, "Código inválido. Confira o horário do celular e tente de novo.")
    u.totp_enabled = True
    db.commit()
    audit(db, request, u, "mfa.enabled")
    return user_out(db, u)


class DisableIn(BaseModel):
    password: str
    code: str


@router.post("/mfa/disable")
def mfa_disable(body: DisableIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(u.password_hash, body.password) or not totp_ok(u.totp_secret, body.code):
        raise HTTPException(400, "Senha ou código inválido.")
    u.totp_enabled = False
    u.totp_secret = None
    db.commit()
    audit(db, request, u, "mfa.disabled")
    return user_out(db, u)
