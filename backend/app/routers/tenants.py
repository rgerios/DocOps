"""Clientes (tenants), membros e usuários da plataforma."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Ctx, audit, ready_user, superadmin, tenant_ctx
from ..models import ROLES, Membership, Tenant, TenantSetting, User
from ..security import hash_password, temp_password

router = APIRouter(tags=["tenants"])

MAX_LOGO = 400_000  # data URL


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "cliente"


def tenant_out(t: Tenant, role: str | None = None, logo=True) -> dict:
    d = {"id": t.id, "name": t.name, "slug": t.slug, "color": t.color, "created_at": t.created_at}
    if logo:
        d["logo"] = t.logo
    if role:
        d["role"] = role
    return d


class TenantIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    color: str | None = None
    logo: str | None = None


@router.get("/api/tenants")
def list_tenants(u: User = Depends(ready_user), db: Session = Depends(get_db)):
    if u.is_superadmin:
        return [tenant_out(t, "admin", logo=False) for t in db.scalars(select(Tenant).order_by(Tenant.name))]
    return sorted([tenant_out(m.tenant, m.role, logo=False) for m in db.scalars(select(Membership).where(Membership.user_id == u.id))],
                  key=lambda x: x["name"].lower())


def _check_branding(body: TenantIn):
    if body.logo and (len(body.logo) > MAX_LOGO or not body.logo.startswith("data:image/")):
        raise HTTPException(400, "Logo inválida: envie PNG, JPG ou SVG de até ~300 KB.")
    if body.color and not re.fullmatch(r"#[0-9a-fA-F]{6}", body.color):
        raise HTTPException(400, "Cor inválida (use #rrggbb).")


@router.post("/api/tenants")
def create_tenant(body: TenantIn, request: Request, u: User = Depends(superadmin), db: Session = Depends(get_db)):
    _check_branding(body)
    slug, n = slugify(body.name), 1
    while db.scalar(select(Tenant).where(Tenant.slug == slug)):
        n += 1
        slug = f"{slugify(body.name)}-{n}"
    t = Tenant(name=body.name.strip(), slug=slug, color=body.color or "#4a7a37", logo=body.logo)
    db.add(t)
    db.flush()
    db.add(TenantSetting(tenant_id=t.id))
    db.commit()
    audit(db, request, u, "tenant.created", t.id, name=t.name)
    return tenant_out(t, "admin")


@router.get("/api/tenants/{tenant_id}")
def get_tenant(c: Ctx = Depends(tenant_ctx("client"))):
    return tenant_out(c.tenant, c.role)


@router.patch("/api/tenants/{tenant_id}")
def update_tenant(body: TenantIn, c: Ctx = Depends(tenant_ctx("admin"))):
    _check_branding(body)
    c.tenant.name = body.name.strip()
    if body.color:
        c.tenant.color = body.color
    if body.logo is not None:
        c.tenant.logo = body.logo or None
    c.db.commit()
    c.audit("tenant.updated", name=c.tenant.name)
    return tenant_out(c.tenant, c.role)


@router.delete("/api/tenants/{tenant_id}")
def delete_tenant(tenant_id: int, request: Request, u: User = Depends(superadmin), db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Cliente não encontrado.")
    name = t.name
    db.delete(t)
    db.commit()
    audit(db, request, u, "tenant.deleted", None, name=name, tenant_id=tenant_id)
    return {"ok": True}


# ── membros do cliente ───────────────────────────────────────────────────────
class MemberIn(BaseModel):
    email: str
    name: str = ""
    role: str = "viewer"


@router.get("/api/tenants/{tenant_id}/members")
def list_members(c: Ctx = Depends(tenant_ctx("admin"))):
    ms = c.db.scalars(select(Membership).where(Membership.tenant_id == c.tenant.id))
    return [{"id": m.id, "user_id": m.user.id, "email": m.user.email, "name": m.user.name, "role": m.role,
             "active": m.user.active, "mfa": m.user.totp_enabled, "last_login": m.user.last_login} for m in ms]


@router.post("/api/tenants/{tenant_id}/members")
def add_member(body: MemberIn, c: Ctx = Depends(tenant_ctx("admin"))):
    if body.role not in ROLES:
        raise HTTPException(400, "Perfil inválido.")
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "E-mail inválido.")
    user = c.db.scalar(select(User).where(func.lower(User.email) == email))
    temp = None
    if not user:
        temp = temp_password()
        user = User(email=email, name=body.name.strip() or email.split("@")[0], password_hash=hash_password(temp), must_change_password=True)
        c.db.add(user)
        c.db.flush()
    if c.db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == c.tenant.id)):
        raise HTTPException(409, "Usuário já tem acesso a este cliente.")
    c.db.add(Membership(user_id=user.id, tenant_id=c.tenant.id, role=body.role))
    c.db.commit()
    c.audit("member.added", email=email, role=body.role, new_user=bool(temp))
    return {"ok": True, "user_id": user.id, "temp_password": temp}


class RoleIn(BaseModel):
    role: str


@router.patch("/api/tenants/{tenant_id}/members/{member_id}")
def set_role(member_id: int, body: RoleIn, c: Ctx = Depends(tenant_ctx("admin"))):
    m = c.db.get(Membership, member_id)
    if not m or m.tenant_id != c.tenant.id:
        raise HTTPException(404, "Membro não encontrado.")
    if body.role not in ROLES:
        raise HTTPException(400, "Perfil inválido.")
    m.role = body.role
    c.db.commit()
    c.audit("member.role", email=m.user.email, role=body.role)
    return {"ok": True}


@router.delete("/api/tenants/{tenant_id}/members/{member_id}")
def remove_member(member_id: int, c: Ctx = Depends(tenant_ctx("admin"))):
    m = c.db.get(Membership, member_id)
    if not m or m.tenant_id != c.tenant.id:
        raise HTTPException(404, "Membro não encontrado.")
    email = m.user.email
    c.db.delete(m)
    c.db.commit()
    c.audit("member.removed", email=email)
    return {"ok": True}


# ── usuários da plataforma (superadmin) ──────────────────────────────────────
class UserIn(BaseModel):
    email: str
    name: str = ""
    is_superadmin: bool = False


class UserPatch(BaseModel):
    name: str | None = None
    active: bool | None = None
    is_superadmin: bool | None = None


@router.get("/api/users")
def list_users(u: User = Depends(superadmin), db: Session = Depends(get_db)):
    out = []
    for x in db.scalars(select(User).order_by(User.email)):
        out.append({"id": x.id, "email": x.email, "name": x.name, "is_superadmin": x.is_superadmin, "active": x.active,
                    "mfa": x.totp_enabled, "last_login": x.last_login, "created_at": x.created_at,
                    "tenants": [{"tenant": m.tenant.name, "role": m.role} for m in x.memberships]})
    return out


@router.post("/api/users")
def create_user(body: UserIn, request: Request, u: User = Depends(superadmin), db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "E-mail inválido.")
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "Já existe um usuário com este e-mail.")
    temp = temp_password()
    x = User(email=email, name=body.name.strip() or email.split("@")[0], password_hash=hash_password(temp),
             is_superadmin=body.is_superadmin, must_change_password=True)
    db.add(x)
    db.commit()
    audit(db, request, u, "user.created", None, email=email, superadmin=body.is_superadmin)
    return {"id": x.id, "temp_password": temp}


@router.patch("/api/users/{user_id}")
def update_user(user_id: int, body: UserPatch, request: Request, u: User = Depends(superadmin), db: Session = Depends(get_db)):
    x = db.get(User, user_id)
    if not x:
        raise HTTPException(404, "Usuário não encontrado.")
    if x.id == u.id and (body.active is False or body.is_superadmin is False):
        raise HTTPException(400, "Você não pode desativar nem rebaixar a própria conta.")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(x, k, v)
    if body.active is False:
        x.session_version += 1
    db.commit()
    audit(db, request, u, "user.updated", None, email=x.email, **body.model_dump(exclude_none=True))
    return {"ok": True}


@router.post("/api/users/{user_id}/reset-password")
def reset_password(user_id: int, request: Request, u: User = Depends(superadmin), db: Session = Depends(get_db)):
    x = db.get(User, user_id)
    if not x:
        raise HTTPException(404, "Usuário não encontrado.")
    temp = temp_password()
    x.password_hash = hash_password(temp)
    x.must_change_password = True
    x.session_version += 1
    x.failed_attempts = 0
    x.locked_until = None
    db.commit()
    audit(db, request, u, "user.password_reset", None, email=x.email)
    return {"temp_password": temp}


@router.post("/api/users/{user_id}/reset-mfa")
def reset_mfa(user_id: int, request: Request, u: User = Depends(superadmin), db: Session = Depends(get_db)):
    x = db.get(User, user_id)
    if not x:
        raise HTTPException(404, "Usuário não encontrado.")
    x.totp_enabled = False
    x.totp_secret = None
    x.session_version += 1
    db.commit()
    audit(db, request, u, "user.mfa_reset", None, email=x.email)
    return {"ok": True}
