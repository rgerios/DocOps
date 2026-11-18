"""Serviço de análise do inventário AWS com LLMs (Copilot, OpenRouter, Gemini, GPT e LLM Local)."""
import json
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Note, Tenant, TenantState
from . import pipeline

PROVIDERS: dict[str, dict[str, str]] = {
    "copilot": {
        "label": "GitHub Copilot",
        "default_model": "gpt-4o",
        "endpoint": "https://models.inference.ai.azure.com/chat/completions",
        "hint": "Token GitHub (PAT) com acesso ao GitHub Models / Copilot.",
    },
    "openrouter": {
        "label": "OpenRouter",
        "default_model": "openai/gpt-4o-mini",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "hint": "Chave sk-or-v1-... do OpenRouter.",
    },
    "gemini": {
        "label": "Google Gemini",
        "default_model": "gemini-2.5-flash",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "hint": "API Key do Google AI Studio (AIza...).",
    },
    "gpt": {
        "label": "OpenAI GPT",
        "default_model": "gpt-4o-mini",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "hint": "Chave sk-... da OpenAI.",
    },
    "local": {
        "label": "LLM Local (Ollama / LM Studio)",
        "default_model": "llama3.1",
        "endpoint": "http://host.docker.internal:11434/v1",
        "hint": "Endpoint compatível com OpenAI (ex.: http://host.docker.internal:11434/v1). Chave opcional.",
    },
}


def mask_key(k: str | None) -> str | None:
    if not k:
        return None
    if len(k) <= 10:
        return "••••"
    return f"{k[:4]}…{k[-4:]}"


def build_inventory_context(db: Session, tenant: Tenant) -> tuple[dict[str, Any], str]:
    """Extrai contadores exatos e um resumo compacto do inventário atual do cliente."""
    cols = pipeline.latest_collections(db, tenant.id)
    st = db.get(TenantState, tenant.id)
    notes = {
        n.key.split("|", 1)[1]: n.data
        for n in db.scalars(select(Note).where(Note.tenant_id == tenant.id, Note.key.like("finding|%")))
    }

    totals: dict[str, Any] = {
        "accounts": 0,
        "ec2_total": 0,
        "ec2_running": 0,
        "ec2_stopped": 0,
        "rds": 0,
        "rds_clusters": 0,
        "vpcs": 0,
        "subnets": 0,
        "security_groups": 0,
        "s3_buckets": 0,
        "lambdas": 0,
        "load_balancers": 0,
        "eks_clusters": 0,
        "ecs_clusters": 0,
        "iam_users": 0,
        "iam_roles": 0,
        "ebs_volumes": 0,
        "findings_open": 0,
        "estimated_monthly_savings_usd": 0.0,
    }
    accounts_ctx = []

    for col in cols:
        p = col.payload or {}
        if not p:
            continue
        totals["accounts"] += 1
        acc_info = p.get("account") or {}
        glob = p.get("global") or {}
        iam = glob.get("iam") or {}
        s3 = glob.get("s3") or []
        users = iam.get("users") or []
        roles = iam.get("roles") or []
        totals["s3_buckets"] += len(s3)
        totals["iam_users"] += len(users)
        totals["iam_roles"] += len(roles)

        regions_ctx = {}
        for rname, rdata in (p.get("regions") or {}).items():
            ec2 = rdata.get("ec2") or []
            vpcs = rdata.get("vpcs") or []
            sgs = rdata.get("security_groups") or []
            rds = rdata.get("rds") or []
            rds_c = rdata.get("rds_clusters") or []
            lbs = rdata.get("load_balancers") or []
            lmb = rdata.get("lambda") or []
            eks = rdata.get("eks") or []
            ecs = rdata.get("ecs") or []
            ebs = rdata.get("ebs_volumes") or []
            sub_cnt = sum(len(v.get("subnets") or []) for v in vpcs)

            totals["ec2_total"] += len(ec2)
            totals["ec2_running"] += sum(1 for i in ec2 if i.get("state") == "running")
            totals["ec2_stopped"] += sum(1 for i in ec2 if i.get("state") == "stopped")
            totals["vpcs"] += len(vpcs)
            totals["subnets"] += sub_cnt
            totals["security_groups"] += len(sgs)
            totals["rds"] += len(rds)
            totals["rds_clusters"] += len(rds_c)
            totals["load_balancers"] += len(lbs)
            totals["lambdas"] += len(lmb)
            totals["eks_clusters"] += len(eks)
            totals["ecs_clusters"] += len(ecs)
            totals["ebs_volumes"] += len(ebs)

            if not any([ec2, vpcs, rds, rds_c, lbs, lmb, eks, ecs, ebs]):
                continue

            regions_ctx[rname] = {
                "vpcs": [{"id": v.get("vpc_id"), "name": v.get("name"), "cidr": v.get("cidr"), "subnets": len(v.get("subnets") or []), "is_default": v.get("is_default")} for v in vpcs[:40]],
                "ec2": [{"id": i.get("id"), "name": i.get("name"), "type": i.get("type"), "state": i.get("state"), "platform": i.get("platform"), "az": i.get("az"), "private_ip": i.get("private_ip"), "public_ip": i.get("public_ip")} for i in ec2[:80]],
                "rds": [{"id": d.get("id"), "engine": d.get("engine"), "version": d.get("engine_version"), "class": d.get("class"), "multi_az": d.get("multi_az"), "public": d.get("publicly_accessible"), "encrypted": d.get("encrypted"), "backup_retention": d.get("backup_retention")} for d in rds[:40]],
                "rds_clusters": [{"id": c.get("id"), "engine": c.get("engine"), "members": len(c.get("members") or [])} for c in rds_c[:20]],
                "load_balancers": [{"name": l.get("name"), "type": l.get("type"), "scheme": l.get("scheme")} for l in lbs[:30]],
                "lambda_count": len(lmb),
                "lambdas": [{"name": f.get("name"), "runtime": f.get("runtime")} for f in lmb[:30]],
                "eks": [e.get("name") for e in eks[:20]],
                "ecs": [e.get("name") for e in ecs[:20]],
                "ebs_count": len(ebs),
                "sgs_open_world": [{"id": s.get("id"), "name": s.get("name"), "open": s.get("open_world")} for s in sgs if s.get("open_world")][:25],
            }

        cost = glob.get("cost") or {}
        finops = glob.get("finops") or {}
        co = finops.get("compute_optimizer") or {}
        sp = finops.get("savings_plans") or {}
        acc_savings = (
            sum(r.get("savings_usd") or 0 for k in ("ec2", "ebs", "lambda") for r in (co.get(k) or []))
            + (sp.get("estimated_monthly_savings_usd") or 0)
        )
        totals["estimated_monthly_savings_usd"] = round(totals["estimated_monthly_savings_usd"] + acc_savings, 2)
        accounts_ctx.append({
            "account_id": acc_info.get("id") or col.account_id,
            "alias": acc_info.get("alias") or col.alias,
            "collected_at": str(col.collected_at or p.get("collected_at") or ""),
            "iam_users_count": len(users),
            "iam_users_no_mfa": [u.get("name") for u in users if not u.get("mfa")][:30],
            "iam_roles_count": len(roles),
            "root_mfa": (iam.get("root") or {}).get("mfa"),
            "s3_count": len(s3),
            "s3_buckets": [{"name": b.get("name"), "region": b.get("region"), "public_blocked": b.get("public_access_blocked"), "lifecycle": b.get("lifecycle"), "size_gb": b.get("size_gb")} for b in s3[:40]],
            "cost": {"currency": cost.get("currency"), "mtd": cost.get("mtd"), "forecast": cost.get("forecast"), "by_service": dict(list((cost.get("by_service") or {}).items())[:12])},
            "finops": finops,
            "regions": regions_ctx,
        })

    findings_list = []
    for f in (st.findings if st else []):
        n = notes.get(f.get("id", "")) or {}
        status = n.get("status", "aberto")
        if status == "aberto":
            totals["findings_open"] += 1
        findings_list.append({
            "severity": f.get("severity"),
            "title": f.get("title"),
            "account": f.get("account_alias") or f.get("account_id"),
            "region": f.get("region"),
            "resource": f.get("resource"),
            "status": status,
        })

    payload = {
        "tenant": tenant.name,
        "totals": totals,
        "accounts": accounts_ctx,
        "findings_sample": findings_list[:60],
    }
    return totals, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def ask_llm(
    provider: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> str:
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Provedor inválido: {provider}")
    meta = PROVIDERS[provider]
    chosen_model = (model or "").strip() or meta["default_model"]

    if provider != "local" and not (api_key or "").strip():
        raise HTTPException(400, f"Informe a chave API para {meta['label']} (ou salve uma nas configurações do cliente).")

    try:
        if provider == "gemini":
            url = f"{meta['endpoint']}/{chosen_model}:generateContent"
            contents = [
                {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages
            ]
            body = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "generationConfig": {"temperature": 0.2},
            }
            resp = httpx.post(url, params={"key": api_key.strip()}, json=body, timeout=90)
            _raise_for_llm_error(resp, meta["label"])
            data = resp.json()
            cands = data.get("candidates") or []
            parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
            text = "".join(p.get("text", "") for p in parts).strip()
            if not text:
                raise HTTPException(502, "O Gemini retornou uma resposta vazia.")
            return text

        # Provedores compatíveis com OpenAI Chat Completions (copilot, openrouter, gpt, local)
        if provider == "local":
            root = (base_url or meta["endpoint"]).strip().rstrip("/")
            url = root if root.endswith("/chat/completions") else f"{root}/chat/completions"
        else:
            url = meta["endpoint"]

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if (api_key or "").strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"
        if provider == "openrouter":
            headers["X-Title"] = "DocOps"

        oai_messages = [{"role": "system", "content": system_prompt}, *messages]
        resp = httpx.post(url, headers=headers, json={"model": chosen_model, "messages": oai_messages, "temperature": 0.2}, timeout=90)
        _raise_for_llm_error(resp, meta["label"])
        data = resp.json()
        choices = data.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
        if not text:
            raise HTTPException(502, f"{meta['label']} retornou uma resposta vazia.")
        return text
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(504, f"Tempo esgotado aguardando resposta de {meta['label']}.")
    except httpx.RequestError as e:
        raise HTTPException(502, f"Não foi possível conectar a {meta['label']}: {e}")


def _raise_for_llm_error(resp: httpx.Response, label: str) -> None:
    if resp.status_code < 400:
        return
    msg = resp.text[:300]
    try:
        err = resp.json().get("error")
        if isinstance(err, dict):
            msg = err.get("message") or msg
        elif isinstance(err, str):
            msg = err
    except Exception:
        pass
    raise HTTPException(502, f"Erro em {label} ({resp.status_code}): {msg}")
