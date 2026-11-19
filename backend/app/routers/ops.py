"""Agendamentos, configurações de alerta, auditoria e relatório PDF."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Ctx, ready_user, superadmin, tenant_ctx
from ..models import AuditLog, Schedule, TenantSetting, User
from ..security import decrypt_secret, encrypt_secret
from ..services import alerts

router = APIRouter(tags=["ops"])
TZ = ZoneInfo(settings.timezone)


# ── agendamentos ─────────────────────────────────────────────────────────────
class ScheduleIn(BaseModel):
    name: str
    cron: str
    account_ids: list[int] | None = None
    enabled: bool = True


def sched_out(s: Schedule) -> dict:
    nxt = croniter(s.cron, datetime.now(TZ)).get_next(datetime) if croniter.is_valid(s.cron) else None
    return {"id": s.id, "name": s.name, "cron": s.cron, "account_ids": s.account_ids, "enabled": s.enabled,
            "last_run": s.last_run, "next_run": nxt, "timezone": settings.timezone}


def _check_cron(cron: str):
    if not croniter.is_valid(cron) or len(cron.split()) != 5:
        raise HTTPException(400, "Expressão cron inválida (5 campos: minuto hora dia mês dia-da-semana).")
    it = croniter(cron, datetime.now(TZ))
    a, b = it.get_next(datetime), it.get_next(datetime)
    if (b - a).total_seconds() < 3600:
        raise HTTPException(400, "Intervalo mínimo entre coletas: 1 hora.")


@router.get("/api/tenants/{tenant_id}/schedules")
def list_schedules(c: Ctx = Depends(tenant_ctx("viewer"))):
    return [sched_out(s) for s in c.db.scalars(select(Schedule).where(Schedule.tenant_id == c.tenant.id).order_by(Schedule.id))]


@router.post("/api/tenants/{tenant_id}/schedules")
def create_schedule(body: ScheduleIn, c: Ctx = Depends(tenant_ctx("admin"))):
    _check_cron(body.cron)
    s = Schedule(tenant_id=c.tenant.id, name=body.name.strip() or "Coleta", cron=body.cron.strip(), account_ids=body.account_ids or None,
                 enabled=body.enabled, last_run=datetime.now(TZ))
    c.db.add(s)
    c.db.commit()
    c.audit("schedule.created", name=s.name, cron=s.cron)
    return sched_out(s)


@router.put("/api/tenants/{tenant_id}/schedules/{sid}")
def update_schedule(sid: int, body: ScheduleIn, c: Ctx = Depends(tenant_ctx("admin"))):
    s = c.db.get(Schedule, sid)
    if not s or s.tenant_id != c.tenant.id:
        raise HTTPException(404, "Agendamento não encontrado.")
    _check_cron(body.cron)
    s.name, s.cron, s.account_ids, s.enabled = body.name.strip() or s.name, body.cron.strip(), body.account_ids or None, body.enabled
    c.db.commit()
    c.audit("schedule.updated", name=s.name, cron=s.cron, enabled=s.enabled)
    return sched_out(s)


@router.delete("/api/tenants/{tenant_id}/schedules/{sid}")
def delete_schedule(sid: int, c: Ctx = Depends(tenant_ctx("admin"))):
    s = c.db.get(Schedule, sid)
    if not s or s.tenant_id != c.tenant.id:
        raise HTTPException(404, "Agendamento não encontrado.")
    c.db.delete(s)
    c.db.commit()
    c.audit("schedule.deleted", name=s.name)
    return {"ok": True}


# ── configurações de alerta ──────────────────────────────────────────────────
class SettingsIn(BaseModel):
    teams_webhook: str | None = None  # None = manter; "" = remover
    alert_severities: list[str] = ["critical", "high"]
    alert_on_failure: bool = True
    alert_on_changes: bool = False


def _cfg(c: Ctx) -> TenantSetting:
    s = c.db.get(TenantSetting, c.tenant.id)
    if not s:
        s = TenantSetting(tenant_id=c.tenant.id)
        c.db.add(s)
        c.db.commit()
    return s


def mask(url: str | None) -> str | None:
    return None if not url else url[:38] + "…" + url[-6:]


@router.get("/api/tenants/{tenant_id}/settings")
def get_settings(c: Ctx = Depends(tenant_ctx("admin"))):
    s = _cfg(c)
    raw_wh = decrypt_secret(s.teams_webhook)
    return {"teams_webhook": mask(raw_wh), "teams_configured": bool(raw_wh), "alert_severities": s.alert_severities,
            "alert_on_failure": s.alert_on_failure, "alert_on_changes": s.alert_on_changes}


@router.put("/api/tenants/{tenant_id}/settings")
def put_settings(body: SettingsIn, c: Ctx = Depends(tenant_ctx("admin"))):
    s = _cfg(c)
    if body.teams_webhook is not None:
        url = body.teams_webhook.strip()
        if url and not re.match(r"^https://[\w.-]+\.(office\.com|office365\.com|microsoft\.com|logic\.azure\.com|powerplatform\.com|powerautomate\.com)(:\d+)?/", url):
            raise HTTPException(400, "URL de webhook do Teams inválida (Workflows/Power Automate ou conector de entrada do Teams).")
        s.teams_webhook = encrypt_secret(url) if url else None
    if any(x not in ("critical", "high", "medium", "low", "info") for x in body.alert_severities):
        raise HTTPException(400, "Severidade inválida.")
    s.alert_severities, s.alert_on_failure, s.alert_on_changes = body.alert_severities, body.alert_on_failure, body.alert_on_changes
    c.db.commit()
    c.audit("settings.updated", teams=bool(s.teams_webhook), severities=s.alert_severities)
    return get_settings(c)


@router.post("/api/tenants/{tenant_id}/settings/test-teams")
def test_teams(c: Ctx = Depends(tenant_ctx("admin"))):
    s = _cfg(c)
    ok, msg = alerts.send(decrypt_secret(s.teams_webhook), f"Teste de alerta — {c.tenant.name}", f"Enviado por {c.user.email} pelo {settings.app_name}.",
                          facts=[("Cliente", c.tenant.name), ("Severidades alertadas", ", ".join(s.alert_severities))])
    return {"ok": ok, "message": "Mensagem enviada ao Teams." if ok else msg}


# ── auditoria ────────────────────────────────────────────────────────────────
def audit_out(a: AuditLog) -> dict:
    return {"id": a.id, "at": a.at, "user": a.user_email, "tenant_id": a.tenant_id, "action": a.action, "detail": a.detail, "ip": a.ip}


@router.get("/api/tenants/{tenant_id}/audit")
def tenant_audit(limit: int = 300, c: Ctx = Depends(tenant_ctx("admin"))):
    q = select(AuditLog).where(AuditLog.tenant_id == c.tenant.id).order_by(AuditLog.id.desc()).limit(min(limit, 2000))
    return [audit_out(a) for a in c.db.scalars(q)]


@router.get("/api/audit")
def platform_audit(limit: int = 300, u: User = Depends(superadmin), db: Session = Depends(get_db)):
    return [audit_out(a) for a in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 2000)))]


# ── relatório PDF ────────────────────────────────────────────────────────────
class PdfIn(BaseModel):
    html: str
    filename: str = "DocOps_Relatorio.pdf"


@router.post("/api/tenants/{tenant_id}/reports/pdf")
def report_pdf(body: PdfIn, request: Request, c: Ctx = Depends(tenant_ctx("viewer"))):
    if len(body.html) > 40_000_000:
        raise HTTPException(400, "Relatório grande demais para PDF; use o HTML.")
    try:
        from weasyprint import HTML  # dependências de sistema instaladas na imagem Docker
    except Exception:  # noqa: BLE001
        raise HTTPException(501, "Geração de PDF indisponível neste servidor (WeasyPrint não instalado).")

    # o relatório é autocontido (logo em data: URL): nenhum recurso externo é buscado
    try:
        from weasyprint.urls import URLFetcher  # WeasyPrint 66+
        fetcher = URLFetcher(allowed_protocols=("data",), timeout=5)
    except ImportError:  # versões antigas aceitam uma função
        from weasyprint.urls import default_url_fetcher

        def fetcher(url, *a, **k):
            if url.startswith("data:"):
                return default_url_fetcher(url)
            raise ValueError("recurso externo bloqueado")

    pdf = HTML(string=body.html, url_fetcher=fetcher).write_pdf()
    c.audit("report.pdf", size=len(pdf))
    name = re.sub(r"[^\w.-]+", "_", body.filename)[:120] or "relatorio.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ── identidade AWS do servidor (para montar a trust policy das roles) ─────────
@router.get("/api/platform/aws-identity")
def aws_identity(u: User = Depends(ready_user)):
    import boto3
    try:
        ident = boto3.Session(region_name=settings.aws_region).client("sts").get_caller_identity()
        arn = ident["Arn"]
        # role assumida (instance profile): arn:aws:sts::<conta>:assumed-role/<role>/<sessão> -> arn da role
        principal = arn
        if ":assumed-role/" in arn:
            role = arn.split(":assumed-role/")[1].split("/")[0]
            principal = f"arn:aws:iam::{ident['Account']}:role/{role}"
        return {"ok": True, "account": ident["Account"], "arn": arn, "principal": principal}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"O servidor ainda não tem credenciais AWS ({type(e).__name__}). Use instance profile no EC2 ou AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY no .env."}
