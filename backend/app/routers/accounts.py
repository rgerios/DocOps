"""Contas AWS de cada cliente e coletas."""
import re
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import undefer

from ..config import settings
from ..deps import Ctx, tenant_ctx
from ..models import AwsAccount, Collection, User
from ..services import diff as diff_svc, pipeline
from ..services.normalize import parse_bytes, to_payloads

router = APIRouter(prefix="/api/tenants/{tenant_id}", tags=["accounts"])
ARN_RE = re.compile(r"^arn:aws:iam::(\d{12}):role/[\w+=,.@/-]{1,512}$")
REGION_RE = re.compile(r"^[a-z]{2}(-gov)?-[a-z]+-\d$")


def acc_out(a: AwsAccount, last: Collection | None = None) -> dict:
    return {"id": a.id, "account_id": a.account_id, "alias": a.alias, "role_arn": a.role_arn, "external_id": a.external_id,
            "regions": a.regions, "environment": a.environment, "active": a.active, "created_at": a.created_at,
            "last_collection": col_out(last) if last else None}


def col_out(c: Collection, users: dict | None = None) -> dict:
    return {"id": c.id, "account_id": c.account_id, "alias": c.alias, "source": c.source, "status": c.status, "trigger": c.trigger,
            "triggered_by": (users or {}).get(c.triggered_by), "error": c.error, "created_at": c.created_at, "started_at": c.started_at,
            "finished_at": c.finished_at, "collected_at": c.collected_at, "summary": c.summary}


class AccountIn(BaseModel):
    account_id: str
    alias: str
    role_arn: str | None = None
    external_id: str | None = None
    regions: list[str] | None = None
    environment: str = ""
    active: bool = True


def _validate(body: AccountIn):
    if not re.fullmatch(r"\d{12}", body.account_id.strip()):
        raise HTTPException(400, "Account ID deve ter 12 dígitos.")
    if body.role_arn:
        m = ARN_RE.match(body.role_arn.strip())
        if not m:
            raise HTTPException(400, "Role ARN inválido (arn:aws:iam::<conta>:role/<nome>).")
        if m.group(1) != body.account_id.strip():
            raise HTTPException(400, "A role precisa ser da mesma conta informada.")
    if body.regions and not all(REGION_RE.match(r) for r in body.regions):
        raise HTTPException(400, "Região inválida na lista.")


@router.get("/accounts")
def list_accounts(c: Ctx = Depends(tenant_ctx("viewer"))):
    last = {x.account_id: x for x in c.db.scalars(select(Collection).where(Collection.tenant_id == c.tenant.id).order_by(Collection.id))}
    return [acc_out(a, last.get(a.account_id)) for a in c.db.scalars(select(AwsAccount).where(AwsAccount.tenant_id == c.tenant.id).order_by(AwsAccount.alias))]


@router.get("/accounts/new-external-id")
def new_external_id(c: Ctx = Depends(tenant_ctx("admin"))):
    return {"external_id": f"docops-{c.tenant.slug}-{secrets.token_hex(8)}"}


@router.post("/accounts")
def create_account(body: AccountIn, c: Ctx = Depends(tenant_ctx("admin"))):
    _validate(body)
    if c.db.scalar(select(AwsAccount).where(AwsAccount.tenant_id == c.tenant.id, AwsAccount.account_id == body.account_id.strip())):
        raise HTTPException(409, "Esta conta já está cadastrada neste cliente.")
    a = AwsAccount(tenant_id=c.tenant.id, account_id=body.account_id.strip(), alias=body.alias.strip() or body.account_id,
                   role_arn=(body.role_arn or "").strip() or None, external_id=(body.external_id or "").strip() or None,
                   regions=body.regions or None, environment=body.environment, active=body.active)
    c.db.add(a)
    c.db.commit()
    c.audit("account.created", account_id=a.account_id, alias=a.alias)
    return acc_out(a)


@router.put("/accounts/{acc_id}")
def update_account(acc_id: int, body: AccountIn, c: Ctx = Depends(tenant_ctx("admin"))):
    a = c.db.get(AwsAccount, acc_id)
    if not a or a.tenant_id != c.tenant.id:
        raise HTTPException(404, "Conta não encontrada.")
    _validate(body)
    if body.account_id.strip() != a.account_id:
        raise HTTPException(400, "O Account ID não pode ser alterado.")
    a.alias, a.role_arn = body.alias.strip() or a.alias, (body.role_arn or "").strip() or None
    a.external_id, a.regions = (body.external_id or "").strip() or None, body.regions or None
    a.environment, a.active = body.environment, body.active
    c.db.commit()
    c.audit("account.updated", account_id=a.account_id)
    return acc_out(a)


@router.delete("/accounts/{acc_id}")
def delete_account(acc_id: int, c: Ctx = Depends(tenant_ctx("admin"))):
    a = c.db.get(AwsAccount, acc_id)
    if not a or a.tenant_id != c.tenant.id:
        raise HTTPException(404, "Conta não encontrada.")
    c.db.delete(a)
    c.db.commit()
    c.audit("account.deleted", account_id=a.account_id)
    return {"ok": True}


@router.post("/accounts/{acc_id}/test")
def test_account(acc_id: int, c: Ctx = Depends(tenant_ctx("analyst"))):
    a = c.db.get(AwsAccount, acc_id)
    if not a or a.tenant_id != c.tenant.id:
        raise HTTPException(404, "Conta não encontrada.")
    if not a.role_arn:
        raise HTTPException(400, "Conta sem role ARN: só aceita upload de arquivo.")
    try:
        sess = pipeline.assume(a)
        ident = sess.client("sts").get_caller_identity()
        regions = [r["RegionName"] for r in sess.client("ec2", region_name=settings.aws_region).describe_regions(AllRegions=False)["Regions"]]
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)[:500]}
    ok = ident["Account"] == a.account_id
    return {"ok": ok, "identity": ident["Arn"], "regions": len(regions),
            "message": "Acesso confirmado." if ok else f"A role pertence à conta {ident['Account']}."}


@router.post("/accounts/{acc_id}/collect")
def collect_one(acc_id: int, c: Ctx = Depends(tenant_ctx("analyst"))):
    a = c.db.get(AwsAccount, acc_id)
    if not a or a.tenant_id != c.tenant.id:
        raise HTTPException(404, "Conta não encontrada.")
    if not a.role_arn:
        raise HTTPException(400, "Conta sem role ARN: importe o arquivo do coletor.")
    running = c.db.scalar(select(Collection).where(Collection.aws_account_id == a.id, Collection.status.in_(("queued", "running"))))
    if running:
        raise HTTPException(409, "Já existe uma coleta em andamento para esta conta.")
    col = pipeline.enqueue_collection(c.db, a, "manual", c.user.id)
    c.audit("collection.started", account_id=a.account_id)
    return col_out(c.db.get(Collection, col.id))


@router.post("/collect-all")
def collect_all(c: Ctx = Depends(tenant_ctx("analyst"))):
    out = []
    for a in c.db.scalars(select(AwsAccount).where(AwsAccount.tenant_id == c.tenant.id, AwsAccount.active.is_(True), AwsAccount.role_arn.is_not(None))):
        if c.db.scalar(select(Collection).where(Collection.aws_account_id == a.id, Collection.status.in_(("queued", "running")))):
            continue
        out.append(pipeline.enqueue_collection(c.db, a, "manual", c.user.id).id)
    c.audit("collection.started_all", count=len(out))
    return {"queued": len(out)}


# ── coletas ──────────────────────────────────────────────────────────────────
@router.get("/collections")
def list_collections(account_id: str | None = None, limit: int = 100, c: Ctx = Depends(tenant_ctx("viewer"))):
    q = select(Collection).where(Collection.tenant_id == c.tenant.id)
    if account_id:
        q = q.where(Collection.account_id == account_id)
    cols = list(c.db.scalars(q.order_by(Collection.id.desc()).limit(min(limit, 500))))
    users = {u.id: u.email for u in c.db.scalars(select(User).where(User.id.in_({x.triggered_by for x in cols if x.triggered_by})))}
    return [col_out(x, users) for x in cols]


@router.get("/collections/compare")
def compare_collections(base_id: int, target_id: int, c: Ctx = Depends(tenant_ctx("viewer"))):
    """Compara quaisquer duas coletas concluídas do mesmo cliente (Diff A × B)."""
    if base_id == target_id:
        raise HTTPException(400, "Selecione duas coletas diferentes para comparar.")
    rows = list(c.db.scalars(
        select(Collection).options(undefer(Collection.payload))
        .where(Collection.tenant_id == c.tenant.id, Collection.id.in_([base_id, target_id]), Collection.status == "done")
    ))
    by_id = {x.id: x for x in rows}
    base, target = by_id.get(base_id), by_id.get(target_id)
    if not base or not target:
        raise HTTPException(404, "Coleta base ou alvo não encontrada (ou ainda não concluída).")
    if bool((base.summary or {}).get("legacy")) != bool((target.summary or {}).get("legacy")):
        raise HTTPException(400, "Não é possível comparar uma coleta legada com uma coleta v2.")
    return {
        "base": col_out(base),
        "target": col_out(target),
        "diff": diff_svc.compare(base.payload, target.payload),
    }


@router.get("/collections/{col_id}")
def get_collection(col_id: int, c: Ctx = Depends(tenant_ctx("viewer"))):
    x = c.db.scalar(select(Collection).options(undefer(Collection.diff)).where(Collection.id == col_id, Collection.tenant_id == c.tenant.id))
    if not x:
        raise HTTPException(404, "Coleta não encontrada.")
    return {**col_out(x), "diff": x.diff}


@router.get("/collections/{col_id}/payload")
def get_payload(col_id: int, c: Ctx = Depends(tenant_ctx("viewer"))):
    x = c.db.scalar(select(Collection).options(undefer(Collection.payload)).where(Collection.id == col_id, Collection.tenant_id == c.tenant.id))
    if not x or not x.payload:
        raise HTTPException(404, "Coleta sem dados.")
    c.audit("collection.downloaded", collection=col_id)
    return x.payload


@router.delete("/collections/{col_id}")
def delete_collection(col_id: int, c: Ctx = Depends(tenant_ctx("admin"))):
    x = c.db.get(Collection, col_id)
    if not x or x.tenant_id != c.tenant.id:
        raise HTTPException(404, "Coleta não encontrada.")
    c.db.delete(x)
    c.db.commit()
    pipeline.refresh_findings(c.db, c.tenant.id)
    c.audit("collection.deleted", collection=col_id, account_id=x.account_id)
    return {"ok": True}


@router.post("/collections/upload")
async def upload(files: list[UploadFile] = File(...), c: Ctx = Depends(tenant_ctx("analyst"))):
    created, errors = [], []
    for f in files:
        raw = await f.read(settings.max_upload_mb * 1024 * 1024 + 1)
        if len(raw) > settings.max_upload_mb * 1024 * 1024:
            errors.append(f"{f.filename}: maior que {settings.max_upload_mb} MB")
            continue
        try:
            payloads = to_payloads(parse_bytes(raw), f.filename or "")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{f.filename}: {e}")
            continue
        for p in payloads:
            acc_id = str((p.get("account") or {}).get("id") or "")
            alias = (p.get("account") or {}).get("alias") or acc_id
            if not re.fullmatch(r"\d{12}", acc_id):
                errors.append(f"{f.filename}: não foi possível identificar o Account ID (use o nome <alias>-<12 dígitos>.json)")
                continue
            a = c.db.scalar(select(AwsAccount).where(AwsAccount.tenant_id == c.tenant.id, AwsAccount.account_id == acc_id))
            if not a:
                a = AwsAccount(tenant_id=c.tenant.id, account_id=acc_id, alias=alias)
                c.db.add(a)
                c.db.flush()
            col = Collection(tenant_id=c.tenant.id, aws_account_id=a.id, account_id=acc_id, alias=a.alias, source="upload",
                             status="running", trigger="upload", triggered_by=c.user.id, payload=p)
            c.db.add(col)
            c.db.commit()
            pipeline.finalize(c.db, col, notify=True)
            created.append({"id": col.id, "account_id": acc_id, "alias": a.alias, "diff": {k: col.diff.get(k) for k in ("baseline", "added", "removed", "changed")}})
    if created:
        c.audit("collection.uploaded", count=len(created), accounts=[x["account_id"] for x in created])
    if not created and errors:
        raise HTTPException(400, " · ".join(errors))
    return {"created": created, "errors": errors}
