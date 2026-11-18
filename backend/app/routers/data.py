"""Inventário consolidado, achados, anotações e documentação do cliente."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from ..deps import Ctx, tenant_ctx
from ..models import Collection, Note, TenantDoc, TenantState, User
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
