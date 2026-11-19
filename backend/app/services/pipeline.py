"""Ciclo de vida das coletas: enfileirar, executar (worker), consolidar achados, diff e alertas."""
import logging
import traceback
from datetime import datetime, timezone

import boto3
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from ..config import settings
from ..db import SessionLocal
from ..models import AwsAccount, Collection, Note, Tenant, TenantSetting, TenantState
from ..security import decrypt_secret
from . import alerts, collector
from .diff import compare
from .findings import compute

log = logging.getLogger("docops.pipeline")
CLOSED = {"resolvido", "aceito"}


def utcnow():
    return datetime.now(timezone.utc)


def _aware(d):
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ── fila ─────────────────────────────────────────────────────────────────────
_fake = None


def get_queue():
    from redis import Redis
    from rq import Queue
    if settings.redis_url.startswith("memory://"):  # testes: executa na hora
        global _fake
        import fakeredis
        _fake = _fake or fakeredis.FakeRedis()
        return Queue("collections", connection=_fake, is_async=False)
    return Queue("collections", connection=Redis.from_url(settings.redis_url),
                 default_timeout=settings.collection_timeout_minutes * 60)


def enqueue_collection(db: Session, acc: AwsAccount, trigger: str = "manual", user_id: int | None = None) -> Collection:
    col = Collection(tenant_id=acc.tenant_id, aws_account_id=acc.id, account_id=acc.account_id, alias=acc.alias,
                     source="assume_role", status="queued", trigger=trigger, triggered_by=user_id)
    db.add(col)
    db.commit()
    get_queue().enqueue(run_collection, col.id, job_id=f"collection-{col.id}")
    return col


# ── consultas ────────────────────────────────────────────────────────────────
def latest_collections(db: Session, tenant_id: int, with_payload=True) -> list[Collection]:
    """Coleta vigente de cada conta: a mais recente, preferindo coletor v2 a arquivos legados.
    Seleciona primeiro os IDs sem carregar payload em memória e só faz undefer nos vencedores.
    """
    q = select(Collection).where(Collection.tenant_id == tenant_id, Collection.status == "done")
    best: dict[str, Collection] = {}
    rank = lambda c: (0 if (c.summary or {}).get("legacy") else 1, _aware(c.collected_at) if c.collected_at else datetime.min.replace(tzinfo=timezone.utc), c.id)
    for c in db.scalars(q):
        cur = best.get(c.account_id)
        if cur is None or rank(c) > rank(cur):
            best[c.account_id] = c
    if not best:
        return []
    if with_payload:
        winner_ids = [c.id for c in best.values()]
        loaded = list(db.scalars(select(Collection).options(undefer(Collection.payload)).where(Collection.id.in_(winner_ids))))
        return sorted(loaded, key=lambda c: c.alias.lower())
    return sorted(best.values(), key=lambda c: c.alias.lower())


def closed_findings(db: Session, tenant_id: int) -> set[str]:
    notes = db.scalars(select(Note).where(Note.tenant_id == tenant_id, Note.key.like("finding|%")))
    return {n.key.split("|", 1)[1] for n in notes if (n.data or {}).get("status") in CLOSED}


def summarize(payload: dict) -> dict:
    regs = payload.get("regions") or {}
    cnt = lambda k: sum(len(r.get(k) or []) for r in regs.values())
    return {"regions": len(regs), "vpcs": sum(1 for r in regs.values() for v in r.get("vpcs") or [] if not v.get("is_default")),
            "subnets": sum(len(v.get("subnets") or []) for r in regs.values() for v in r.get("vpcs") or [] if not v.get("is_default")),
            "ec2": cnt("ec2"), "rds": cnt("rds") + cnt("rds_clusters"), "lambda": cnt("lambda"), "containers": cnt("ecs") + cnt("eks"),
            "load_balancers": cnt("load_balancers"), "s3": len((payload.get("global") or {}).get("s3") or []),
            "errors": len(payload.get("errors") or []), "legacy": bool(payload.get("legacy")),
            "collector_version": payload.get("collector_version"), "duration_s": payload.get("duration_s")}


# ── consolidação ─────────────────────────────────────────────────────────────
def finalize(db: Session, col: Collection, notify: bool = True):
    """Marca a coleta como concluída, calcula diff contra a anterior e reprocessa os achados do cliente."""
    payload = col.payload or {}
    col.summary = summarize(payload)
    col.collected_at = datetime.fromisoformat(payload["collected_at"].replace("Z", "+00:00")) if payload.get("collected_at") else utcnow()
    prev = db.scalar(select(Collection).options(undefer(Collection.payload)).where(
        Collection.tenant_id == col.tenant_id, Collection.account_id == col.account_id, Collection.status == "done",
        Collection.id != col.id).order_by(Collection.collected_at.desc().nulls_last(), Collection.id.desc()).limit(1))
    if prev and prev.collected_at and col.collected_at and _aware(prev.collected_at) > _aware(col.collected_at):
        prev = None  # arquivo antigo importado depois: não compara "para trás"
    if prev and bool((prev.summary or {}).get("legacy")) != bool(col.summary.get("legacy")):
        prev = None  # formatos diferentes (legado x v2) não geram um diff útil
    col.diff = compare(prev.payload if prev else None, payload)
    col.summary = {**col.summary, "diff": {k: col.diff.get(k) for k in ("baseline", "added", "removed", "changed")}}
    col.status = "done"
    col.finished_at = utcnow()
    db.commit()
    refresh_findings(db, col.tenant_id, col if notify else None)


def refresh_findings(db: Session, tenant_id: int, trigger_col: Collection | None = None) -> list[dict]:
    cols = latest_collections(db, tenant_id)
    found = compute([c.payload for c in cols if c.payload])
    st = db.get(TenantState, tenant_id)
    before = {f["id"] for f in (st.findings if st else [])}
    if st:
        st.findings, st.computed_at = found, utcnow()
    else:
        db.add(TenantState(tenant_id=tenant_id, findings=found, computed_at=utcnow()))
    db.commit()
    if trigger_col is not None and st is not None:  # primeira consolidação não alerta (seria tudo "novo")
        cfg = db.get(TenantSetting, tenant_id)
        webhook = decrypt_secret(cfg.teams_webhook) if cfg else None
        if cfg and webhook:
            closed = closed_findings(db, tenant_id)
            new = [f for f in found if f["id"] not in before and f["id"] not in closed and f["sev"] in (cfg.alert_severities or [])]
            tenant = db.get(Tenant, tenant_id)
            if new:
                alerts.send(webhook, f"{len(new)} novo(s) achado(s) em {tenant.name}",
                            f"Após a coleta da conta {trigger_col.alias} ({trigger_col.account_id})", items=new)
            d = trigger_col.diff or {}
            if cfg.alert_on_changes and not d.get("baseline") and (d.get("added") or d.get("removed") or d.get("changed")):
                alerts.send(webhook, f"Mudanças na conta {trigger_col.alias}", tenant.name,
                            facts=[("Novos", str(d.get("added", 0))), ("Removidos", str(d.get("removed", 0))), ("Alterados", str(d.get("changed", 0)))])
    return found


# ── job do worker ────────────────────────────────────────────────────────────
def assume(acc: AwsAccount):
    base = boto3.Session(region_name=settings.aws_region)
    kw = {"RoleArn": acc.role_arn, "RoleSessionName": "docops-collector", "DurationSeconds": 3600}
    if acc.external_id:
        kw["ExternalId"] = acc.external_id
    cr = base.client("sts").assume_role(**kw)["Credentials"]
    return boto3.Session(aws_access_key_id=cr["AccessKeyId"], aws_secret_access_key=cr["SecretAccessKey"],
                         aws_session_token=cr["SessionToken"], region_name=settings.aws_region)


def run_collection(collection_id: int):
    db = SessionLocal()
    col = db.get(Collection, collection_id)
    if not col:
        return
    acc = db.get(AwsAccount, col.aws_account_id) if col.aws_account_id else None
    col.status, col.started_at = "running", utcnow()
    db.commit()
    try:
        if not acc or not acc.role_arn:
            raise RuntimeError("Conta sem role ARN configurada.")
        sess = assume(acc)
        opts = collector.default_opts(regions=acc.regions or None, home_region=settings.aws_region,
                                      workers=settings.collector_workers, inner_workers=settings.collector_inner_workers,
                                      no_cost=not settings.collector_cost_explorer)
        payload = collector.to_jsonable(collector.collect_account(sess, opts, acc.alias))
        got = payload["account"]["id"]
        if got != acc.account_id:
            raise RuntimeError(f"A role assumida pertence à conta {got}, não à {acc.account_id}.")
        col.payload = payload
        finalize(db, col)
    except Exception as e:  # noqa: BLE001
        log.error("coleta %s falhou: %s", collection_id, traceback.format_exc())
        col.status, col.error, col.finished_at = "failed", str(e)[:2000], utcnow()
        db.commit()
        cfg = db.get(TenantSetting, col.tenant_id)
        webhook = decrypt_secret(cfg.teams_webhook) if cfg else None
        if cfg and webhook and cfg.alert_on_failure:
            t = db.get(Tenant, col.tenant_id)
            alerts.send(webhook, f"Falha na coleta da conta {col.alias}", t.name if t else "",
                        facts=[("Conta", col.account_id), ("Erro", str(e)[:300])])
    finally:
        db.close()
