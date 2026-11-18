import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from . import models  # noqa: F401  (registra as tabelas)
from .config import settings
from .db import Base, SessionLocal, engine
from .models import User
from .routers import accounts, auth, data, ops, tenants
from .security import hash_password, password_problems

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("docops")

@asynccontextmanager
async def lifespan(_app):
    bootstrap()
    yield


app = FastAPI(title=f"{settings.app_name} API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None,
              lifespan=lifespan)


@app.middleware("http")
async def guard(request: Request, call_next):
    # CSRF: o cookie de sessão é SameSite=Strict e, além disso, toda escrita exige um cabeçalho que
    # navegadores só enviam em chamadas feitas pelo próprio front (formulários de outros sites não conseguem).
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/") \
            and request.headers.get("x-docops") != "1":
        return JSONResponse({"detail": "Requisição recusada (cabeçalho X-DocOps ausente)."}, status_code=403)
    resp = await call_next(request)
    resp.headers.setdefault("Cache-Control", "no-store")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    return resp


for r in (auth.router, tenants.router, accounts.router, data.router, ops.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    with engine.connect() as c:
        c.execute(text("select 1"))
    return {"ok": True, "app": settings.app_name}


def bootstrap():
    """Cria as tabelas e o primeiro administrador (só quando o banco ainda não tem usuários)."""
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(User).limit(1)):
            return
        if not settings.admin_password or password_problems(settings.admin_password):
            log.warning("Nenhum usuário no banco e ADMIN_PASSWORD ausente ou fraca: defina-a no .env para criar o primeiro admin.")
            return
        db.add(User(email=settings.admin_email.lower(), name="Administrador", password_hash=hash_password(settings.admin_password),
                    is_superadmin=True, must_change_password=True))
        db.commit()
        log.info("Administrador inicial criado: %s (troca de senha obrigatória no primeiro acesso)", settings.admin_email)

