"""Dependências de autenticação, autorização por cliente e auditoria."""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import ROLE_LEVEL, AuditLog, Membership, Tenant, User
from .security import COOKIE, read_session


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    s = read_session(token) if token else None
    if not s:
        raise HTTPException(401, "Sessão expirada. Entre novamente.")
    user = db.get(User, s[0])
    if not user or not user.active or user.session_version != s[1]:
        raise HTTPException(401, "Sessão inválida. Entre novamente.")
    return user


def ready_user(user: User = Depends(current_user)) -> User:
    """Usuário autenticado que já trocou a senha provisória."""
    if user.must_change_password:
        raise HTTPException(403, "Troque a senha provisória antes de continuar.")
    return user


def superadmin(user: User = Depends(ready_user)) -> User:
    if not user.is_superadmin:
        raise HTTPException(403, "Apenas administradores da plataforma.")
    return user


def role_in(db: Session, user: User, tenant_id: int) -> str | None:
    if user.is_superadmin:
        return "admin"
    m = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tenant_id))
    return m.role if m else None


@dataclass
class Ctx:
    user: User
    tenant: Tenant
    role: str
    db: Session
    request: Request

    def audit(self, action: str, **detail):
        audit(self.db, self.request, self.user, action, self.tenant.id, **detail)


def tenant_ctx(min_role: str):
    def dep(tenant_id: int, request: Request, user: User = Depends(ready_user), db: Session = Depends(get_db)) -> Ctx:
        t = db.get(Tenant, tenant_id)
        if not t:
            raise HTTPException(404, "Cliente não encontrado.")
        role = role_in(db, user, tenant_id)
        if role is None or ROLE_LEVEL[role] < ROLE_LEVEL[min_role]:
            raise HTTPException(403, "Sem permissão para esta ação neste cliente.")
        return Ctx(user, t, role, db, request)
    return dep


def audit(db: Session, request: Request | None, user: User | None, action: str, tenant_id: int | None = None, **detail):
    db.add(AuditLog(user_id=user.id if user else None, user_email=user.email if user else "", tenant_id=tenant_id,
                    action=action, detail=detail or None, ip=client_ip(request) if request else ""))
    db.commit()
