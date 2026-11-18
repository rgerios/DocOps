"""Endpoints de configuração e análise com IA do inventário do cliente."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import Ctx, tenant_ctx
from ..models import TenantAIConfig
from ..services.ai import PROVIDERS, ask_llm, build_inventory_context, mask_key

router = APIRouter(prefix="/api/tenants/{tenant_id}/ai", tags=["ai"])


class AIConfigIn(BaseModel):
    provider: str = "gpt"
    model: str = ""
    base_url: str | None = None
    api_key: str | None = None  # None mantém a salva; "" limpa


class ChatMsg(BaseModel):
    role: str
    content: str


class AskIn(BaseModel):
    question: str
    history: list[ChatMsg] = []
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


def _config_out(cfg: TenantAIConfig | None, totals: dict) -> dict:
    prov = cfg.provider if cfg and cfg.provider in PROVIDERS else "gpt"
    return {
        "provider": prov,
        "model": (cfg.model if cfg else "") or PROVIDERS[prov]["default_model"],
        "base_url": (cfg.base_url if cfg else None) or "",
        "api_key_configured": bool(cfg and cfg.api_key),
        "api_key_hint": mask_key(cfg.api_key) if cfg else None,
        "providers": PROVIDERS,
        "stats": totals,
    }


@router.get("/config")
def get_ai_config(c: Ctx = Depends(tenant_ctx("viewer"))):
    cfg = c.db.get(TenantAIConfig, c.tenant.id)
    totals, _ = build_inventory_context(c.db, c.tenant)
    return _config_out(cfg, totals)


@router.put("/config")
def put_ai_config(body: AIConfigIn, c: Ctx = Depends(tenant_ctx("admin"))):
    if body.provider not in PROVIDERS:
        raise HTTPException(400, "Provedor de IA inválido.")
    cfg = c.db.get(TenantAIConfig, c.tenant.id)
    if not cfg:
        cfg = TenantAIConfig(tenant_id=c.tenant.id)
        c.db.add(cfg)
    cfg.provider = body.provider
    cfg.model = body.model.strip() or PROVIDERS[body.provider]["default_model"]
    cfg.base_url = (body.base_url or "").strip() or None
    if body.api_key is not None:
        cfg.api_key = body.api_key.strip() or None
    cfg.updated_by = c.user.id
    c.db.commit()
    c.audit("ai.config_updated", provider=cfg.provider, model=cfg.model)
    totals, _ = build_inventory_context(c.db, c.tenant)
    return _config_out(cfg, totals)


@router.post("/ask")
def ask_ai(body: AskIn, c: Ctx = Depends(tenant_ctx("viewer"))):
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "Informe uma pergunta.")
    if len(q) > 8000:
        raise HTTPException(400, "Pergunta longa demais.")

    cfg = c.db.get(TenantAIConfig, c.tenant.id)
    provider = body.provider or (cfg.provider if cfg else "gpt")
    if provider not in PROVIDERS:
        raise HTTPException(400, "Provedor de IA inválido.")

    model = (body.model or "").strip() or (cfg.model if cfg and cfg.provider == provider else PROVIDERS[provider]["default_model"])
    base_url = (body.base_url or "").strip() or (cfg.base_url if cfg and cfg.provider == provider else None)
    api_key = (body.api_key or "").strip() or (cfg.api_key if cfg and cfg.provider == provider else None)

    totals, context_json = build_inventory_context(c.db, c.tenant)
    if totals["accounts"] == 0:
        raise HTTPException(400, "Este cliente ainda não possui coletas concluídas para análise.")

    system_prompt = (
        "Você é um arquiteto cloud sênior analisando o inventário AWS real do cliente no DocOps.\n"
        "Responda sempre em português do Brasil, de forma clara, estruturada (use títulos curtos, listas e tabelas Markdown quando ajudar) "
        "e 100% fiel aos dados fornecidos abaixo.\n"
        "Use exatamente os contadores de `totals` e os detalhes de `accounts` e `findings_sample`. "
        "Se alguma informação não estiver presente nos dados coletados, diga explicitamente que não foi coletada.\n\n"
        f"INVENTARIO_ATUAL_JSON:\n{context_json}"
    )

    msgs = [{"role": m.role, "content": m.content} for m in body.history[-8:] if m.role in ("user", "assistant") and m.content.strip()]
    msgs.append({"role": "user", "content": q})

    answer = ask_llm(provider, model, api_key, base_url, system_prompt, msgs)
    c.audit("ai.asked", provider=provider, model=model)
    return {"answer": answer, "provider": provider, "model": model, "stats": totals}
