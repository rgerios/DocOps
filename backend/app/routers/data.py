"""Inventário consolidado, achados, anotações e documentação do cliente."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from ..deps import Ctx, tenant_ctx
from ..models import Collection, Note, TenantDoc, TenantState, User
from ..services import overview as overview_svc
from ..services import pipeline

router = APIRouter(prefix="/api/tenants/{tenant_id}", tags=["data"])
MAX_NOTE = 20_000


@router.get("/inventory")
def inventory(
    collection_id: int | None = Query(default=None),
    collection_ids: str | None = Query(default=None),
    c: Ctx = Depends(tenant_ctx("client")),
):
    """Tudo que o Explorer precisa: coleta vigente (ou histórica selecionada) de cada conta, versões, anotações e marca."""
    cols = pipeline.latest_collections(c.db, c.tenant.id)
    by_account = {x.account_id: x for x in cols}

    wanted_ids: list[int] = []
    if collection_id is not None:
        wanted_ids.append(collection_id)
    if collection_ids:
        for part in collection_ids.split(","):
            part = part.strip()
            if part.isdigit():
                wanted_ids.append(int(part))

    if wanted_ids:
        overrides = list(
            c.db.scalars(
                select(Collection).where(
                    Collection.tenant_id == c.tenant.id,
                    Collection.id.in_(wanted_ids),
                    Collection.status == "done",
                )
            )
        )
        for ov in overrides:
            if ov.payload:
                by_account[ov.account_id] = ov
        cols = list(by_account.values())

    all_done = list(
        c.db.scalars(
            select(Collection)
            .where(Collection.tenant_id == c.tenant.id, Collection.status == "done")
            .order_by(desc(Collection.collected_at), desc(Collection.id))
        )
    )
    versions: dict[str, list[dict]] = {}
    for x in all_done:
        versions.setdefault(x.account_id, []).append({
            "id": x.id,
            "account_id": x.account_id,
            "alias": x.alias,
            "source": x.source,
            "trigger": x.trigger,
            "collected_at": x.collected_at,
            "created_at": x.created_at,
            "summary": x.summary,
        })

    notes = {n.key: n.data for n in c.db.scalars(select(Note).where(Note.tenant_id == c.tenant.id))}
    if c.role == "client":  # cliente vê o ambiente e as tratativas, não as anotações internas
        notes = {k: v for k, v in notes.items() if k.startswith("finding|")}
    doc = c.db.get(TenantDoc, c.tenant.id)
    return {
        "tenant": {"id": c.tenant.id, "name": c.tenant.name, "logo": c.tenant.logo, "color": c.tenant.color},
        "role": c.role,
        "accounts": [x.payload for x in cols if x.payload],
        "notes": notes,
        "docs": (doc.data if doc else {}) or {},
        "collections": [{"id": x.id, "account_id": x.account_id, "alias": x.alias, "collected_at": x.collected_at, "source": x.source, "trigger": x.trigger} for x in cols],
        "versions": versions,
    }


@router.get("/findings")
def findings(c: Ctx = Depends(tenant_ctx("client"))):
    st = c.db.get(TenantState, c.tenant.id)
    found = st.findings if st else []
    notes = {n.key.split("|", 1)[1]: n.data for n in c.db.scalars(select(Note).where(Note.tenant_id == c.tenant.id, Note.key.like("finding|%")))}
    for f in found:
        n = notes.get(f["id"]) or {}
        f["status"], f["owner"], f["note"] = n.get("status", "aberto"), n.get("owner"), n.get("text")
    return {"computed_at": st.computed_at if st else None, "findings": found}


@router.post("/findings/recompute")
def recompute_findings(c: Ctx = Depends(tenant_ctx("analyst"))):
    """Recalcula os achados (incluindo regras FinOps/Well-Architected) sobre as coletas vigentes."""
    pipeline.refresh_findings(c.db, c.tenant.id)
    c.audit("findings.recomputed")
    return findings(c)


@router.get("/finops")
def finops_overview(c: Ctx = Depends(tenant_ctx("viewer"))):
    """Resumo financeiro, alvos Well-Architected (COST05-COST08) e achados de custo do cliente."""
    cols = pipeline.latest_collections(c.db, c.tenant.id)
    st = c.db.get(TenantState, c.tenant.id)
    notes = {n.key.split("|", 1)[1]: n.data for n in c.db.scalars(select(Note).where(Note.tenant_id == c.tenant.id, Note.key.like("finding|%")))}

    finops_findings = []
    for f in (st.findings if st else []):
        if f.get("cat") not in ("Custo", "Well-Architected"):
            continue
        item = dict(f)
        n = notes.get(item["id"]) or {}
        item["status"], item["owner"], item["note"] = n.get("status", "aberto"), n.get("owner"), n.get("text")
        finops_findings.append(item)

    summary = {
        "accounts": 0,
        "estimated_monthly_savings_usd": 0.0,
        "mtd_cost_usd": 0.0,
        "forecast_cost_usd": 0.0,
        "gp2_volumes": 0,
        "unattached_ebs": 0,
        "unused_eips": 0,
        "old_gen_ec2": 0,
        "old_gen_rds": 0,
        "s3_no_lifecycle": 0,
        "old_snapshots": 0,
        "nat_no_endpoint": 0,
        "well_architected_risks": 0,
    }
    accounts_cost = []

    for col in cols:
        p = col.payload or {}
        if not p:
            continue
        summary["accounts"] += 1
        glob = p.get("global") or {}
        cost = glob.get("cost") or {}
        fin = glob.get("finops") or {}
        co = fin.get("compute_optimizer") or {}
        sp = fin.get("savings_plans") or {}
        wa = fin.get("well_architected") or []

        mtd = float(cost.get("mtd") or 0)
        fc = float(cost.get("forecast") or 0)
        summary["mtd_cost_usd"] = round(summary["mtd_cost_usd"] + mtd, 2)
        summary["forecast_cost_usd"] = round(summary["forecast_cost_usd"] + fc, 2)

        co_recs = [r for k in ("ec2", "ebs", "lambda") for r in (co.get(k) or [])]
        acc_sav = sum(float(r.get("savings_usd") or 0) for r in co_recs) + float(sp.get("estimated_monthly_savings_usd") or 0)
        summary["estimated_monthly_savings_usd"] = round(summary["estimated_monthly_savings_usd"] + acc_sav, 2)
        summary["well_architected_risks"] += sum((w.get("high") or 0) + (w.get("medium") or 0) for w in wa)

        for b in glob.get("s3") or []:
            if b.get("lifecycle") is False:
                summary["s3_no_lifecycle"] += 1

        for rdata in (p.get("regions") or {}).values():
            for v in rdata.get("ebs_volumes") or []:
                if v.get("type") == "gp2":
                    summary["gp2_volumes"] += 1
                if v.get("state") == "available":
                    summary["unattached_ebs"] += 1
            for e in rdata.get("eips") or []:
                if not e.get("associated"):
                    summary["unused_eips"] += 1
            for i in rdata.get("ec2") or []:
                if i.get("state") == "running" and str(i.get("type") or "").startswith(("t2.", "m4.", "c4.", "r4.")):
                    summary["old_gen_ec2"] += 1
            for d in rdata.get("rds") or []:
                if str(d.get("class") or "").startswith(("db.t2.", "db.m4.", "db.r4.")):
                    summary["old_gen_rds"] += 1
            summary["old_snapshots"] += int((rdata.get("ebs_snapshots_summary") or {}).get("older_than_365d") or 0)
            for vpc in rdata.get("vpcs") or []:
                if vpc.get("nat_gws"):
                    has_gw = any("s3" in str(ep.get("service") or "") or "dynamodb" in str(ep.get("service") or "") for ep in (vpc.get("endpoints") or []))
                    if not has_gw:
                        summary["nat_no_endpoint"] += 1

        accounts_cost.append({
            "account_id": col.account_id,
            "alias": col.alias,
            "currency": cost.get("currency") or "USD",
            "mtd": cost.get("mtd"),
            "forecast": cost.get("forecast"),
            "estimated_savings_usd": round(acc_sav, 2),
            "co_count": len(co_recs),
            "savings_plans": sp or None,
            "well_architected": wa,
        })

    return {
        "computed_at": st.computed_at if st else None,
        "summary": summary,
        "accounts": accounts_cost,
        "findings": finops_findings,
    }


def _findings_with_notes(c: Ctx) -> list[dict]:
    st = c.db.get(TenantState, c.tenant.id)
    notes = {
        n.key.split("|", 1)[1]: n.data
        for n in c.db.scalars(select(Note).where(Note.tenant_id == c.tenant.id, Note.key.like("finding|%")))
    }
    out = []
    for f in (st.findings if st else []):
        item = dict(f)
        n = notes.get(item["id"]) or {}
        item["status"] = n.get("status", "aberto")
        item["owner"] = n.get("owner")
        item["note"] = n.get("text")
        out.append(item)
    return out


@router.get("/overview")
def tenant_overview(
    account_id: str | None = Query(default=None),
    c: Ctx = Depends(tenant_ctx("viewer")),
):
    """Panorama Geral: Raio-X da Conta (8 pilares reais 0-100) + Benchmark & Camadas Concêntricas."""
    cols = pipeline.latest_collections(c.db, c.tenant.id)
    found = _findings_with_notes(c)
    res = overview_svc.build_overview(cols, found, account_id=account_id)
    st = c.db.get(TenantState, c.tenant.id)
    res["computedAt"] = st.computed_at if st else None
    return res


@router.get("/assets")
def tenant_assets(
    account_id: str | None = Query(default=None),
    c: Ctx = Depends(tenant_ctx("viewer")),
):
    """Inventário tabular unificado de recursos AWS com status, tags e achados."""
    cols = pipeline.latest_collections(c.db, c.tenant.id)
    found = _findings_with_notes(c)
    return overview_svc.build_assets(cols, found, account_id=account_id)


class NotesIn(BaseModel):
    changes: dict[str, dict | None]  # chave -> dados (None apaga)


@router.put("/notes")
def save_notes(body: NotesIn, c: Ctx = Depends(tenant_ctx("analyst"))):
    if len(body.changes) > 500:
        raise HTTPException(400, "Muitas alterações de uma vez.")
    existing = {n.key: n for n in c.db.scalars(select(Note).where(Note.tenant_id == c.tenant.id, Note.key.in_(list(body.changes))))}
    for k, v in body.changes.items():
        if len(k) > 600:
            raise HTTPException(400, "Chave de anotação longa demais.")
        n = existing.get(k)
        if v is None or (not (v.get("text") or "").strip() and not v.get("status") and not v.get("owner")):
            if n:
                c.db.delete(n)
            continue
        if len(str(v.get("text", ""))) > MAX_NOTE:
            raise HTTPException(400, "Anotação longa demais.")
        data = {"text": v.get("text", ""), "at": v.get("at")}
        for f in ("status", "owner"):
            if v.get(f):
                data[f] = str(v[f])[:200]
        data["by"] = c.user.name or c.user.email
        if n:
            n.data, n.updated_by = data, c.user.id
        else:
            c.db.add(Note(tenant_id=c.tenant.id, key=k, data=data, updated_by=c.user.id))
    c.db.commit()
    statuses = {k: (v or {}).get("status") for k, v in body.changes.items() if k.startswith("finding|") and v}
    c.audit("notes.saved", keys=list(body.changes)[:50], finding_status=statuses or None)
    return {"ok": True}


class DocsIn(BaseModel):
    data: dict


@router.get("/docs")
def get_docs(c: Ctx = Depends(tenant_ctx("viewer"))):
    d = c.db.get(TenantDoc, c.tenant.id)
    who = c.db.get(User, d.updated_by) if d and d.updated_by else None
    return {"data": (d.data if d else {}) or {}, "updated_at": d.updated_at if d else None, "updated_by": who.email if who else None}


@router.put("/docs")
def put_docs(body: DocsIn, c: Ctx = Depends(tenant_ctx("analyst"))):
    if len(str(body.data)) > 500_000:
        raise HTTPException(400, "Documentação grande demais.")
    d = c.db.get(TenantDoc, c.tenant.id)
    if d:
        d.data, d.updated_by = body.data, c.user.id
    else:
        c.db.add(TenantDoc(tenant_id=c.tenant.id, data=body.data, updated_by=c.user.id))
    c.db.commit()
    c.audit("docs.saved")
    return {"ok": True}
