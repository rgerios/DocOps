"""Endpoints de configuração e análise com IA do inventário do cliente."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..deps import Ctx, tenant_ctx
from ..models import AiConversation, TenantAIConfig
from ..security import decrypt_secret, encrypt_secret
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
    conversation_id: int | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


def _config_out(cfg: TenantAIConfig | None, totals: dict) -> dict:
    prov = cfg.provider if cfg and cfg.provider in PROVIDERS else "gpt"
    raw_key = decrypt_secret(cfg.api_key) if cfg else None
    return {
        "provider": prov,
        "model": (cfg.model if cfg else "") or PROVIDERS[prov]["default_model"],
        "base_url": (cfg.base_url if cfg else None) or "",
        "api_key_configured": bool(raw_key),
        "api_key_hint": mask_key(raw_key) if raw_key else None,
        "providers": PROVIDERS,
        "stats": totals,
    }


def _conv_summary(conv: AiConversation) -> dict:
    msgs = conv.messages or []
    return {
        "id": conv.id,
        "title": conv.title,
        "provider": conv.provider,
        "model": conv.model,
        "message_count": len(msgs),
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
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
        clean_key = body.api_key.strip()
        cfg.api_key = encrypt_secret(clean_key) if clean_key else None
    cfg.updated_by = c.user.id
    c.db.commit()
    c.audit("ai.config_updated", provider=cfg.provider, model=cfg.model)
    totals, _ = build_inventory_context(c.db, c.tenant)
    return _config_out(cfg, totals)


@router.get("/history")
def list_history(c: Ctx = Depends(tenant_ctx("viewer"))):
    rows = list(c.db.scalars(
        select(AiConversation)
        .where(AiConversation.tenant_id == c.tenant.id)
        .order_by(AiConversation.updated_at.desc(), AiConversation.id.desc())
        .limit(30)
    ))
    return [_conv_summary(x) for x in rows]


@router.get("/history/{conv_id}")
def get_history(conv_id: int, c: Ctx = Depends(tenant_ctx("viewer"))):
    conv = c.db.get(AiConversation, conv_id)
    if not conv or conv.tenant_id != c.tenant.id:
        raise HTTPException(404, "Conversa não encontrada.")
    return {**_conv_summary(conv), "messages": conv.messages or []}


@router.delete("/history/{conv_id}")
def delete_history(conv_id: int, c: Ctx = Depends(tenant_ctx("analyst"))):
    conv = c.db.get(AiConversation, conv_id)
    if not conv or conv.tenant_id != c.tenant.id:
        raise HTTPException(404, "Conversa não encontrada.")
    c.db.delete(conv)
    c.db.commit()
    c.audit("ai.history_deleted", conversation_id=conv_id)
    return {"ok": True}


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
    saved_key = decrypt_secret(cfg.api_key) if cfg and cfg.provider == provider else None
    api_key = (body.api_key or "").strip() or saved_key

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

    conv: AiConversation | None = None
    if body.conversation_id:
        conv = c.db.get(AiConversation, body.conversation_id)
        if not conv or conv.tenant_id != c.tenant.id:
            conv = None

    prior = (conv.messages if conv else [{"role": m.role, "content": m.content} for m in body.history]) or []
    msgs = [{"role": m["role"], "content": m["content"]} for m in prior[-8:] if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()]
    msgs.append({"role": "user", "content": q})

    answer = ask_llm(provider, model, api_key, base_url, system_prompt, msgs)

    now_iso = datetime.now(timezone.utc).isoformat()
    new_turns = [
        {"role": "user", "content": q, "at": now_iso},
        {"role": "assistant", "content": answer, "provider": provider, "model": model, "at": now_iso},
    ]
    if conv:
        conv.messages = [*(conv.messages or []), *new_turns][-40:]
        conv.provider = provider
        conv.model = model
        conv.updated_at = datetime.now(timezone.utc)
    else:
        title = q.replace("\n", " ").strip()[:120]
        conv = AiConversation(
            tenant_id=c.tenant.id,
            user_id=c.user.id,
            title=title or "Análise IA",
            provider=provider,
            model=model,
            messages=[*prior[-10:], *new_turns][-40:],
        )
        c.db.add(conv)
    c.db.commit()
    c.db.refresh(conv)

    c.audit("ai.asked", provider=provider, model=model, conversation_id=conv.id)
    return {
        "answer": answer,
        "provider": provider,
        "model": model,
        "stats": totals,
        "conversation_id": conv.id,
        "conversation": _conv_summary(conv),
    }
