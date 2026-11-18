"""Alertas no Microsoft Teams (webhook de entrada / Workflows)."""
import logging

import httpx

from .findings import SEV_LABEL

log = logging.getLogger("docops.alerts")
SEV_COLOR = {"critical": "Attention", "high": "Warning", "medium": "Accent", "low": "Default", "info": "Default"}


def _card(title: str, subtitle: str, facts: list[tuple[str, str]], items: list[dict] | None = None, url: str | None = None) -> dict:
    body = [{"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": title, "wrap": True},
            {"type": "TextBlock", "spacing": "None", "isSubtle": True, "text": subtitle, "wrap": True}]
    if facts:
        body.append({"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in facts]})
    for it in (items or [])[:12]:
        body.append({"type": "TextBlock", "wrap": True, "spacing": "Small", "color": SEV_COLOR.get(it.get("sev"), "Default"),
                     "text": f"**{SEV_LABEL.get(it.get('sev'), '')}** · {it['title']} — {it.get('resource', '')} ({it.get('account', '')}/{it.get('region', '')})"})
    if items and len(items) > 12:
        body.append({"type": "TextBlock", "isSubtle": True, "text": f"+ {len(items) - 12} outros"})
    card = {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "version": "1.4", "body": body}
    if url:
        card["actions"] = [{"type": "Action.OpenUrl", "title": "Abrir no DocOps", "url": url}]
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}


def send(webhook: str | None, title: str, subtitle: str, facts=None, items=None, url=None) -> tuple[bool, str]:
    if not webhook:
        return False, "Webhook do Teams não configurado."
    try:
        r = httpx.post(webhook, json=_card(title, subtitle, facts or [], items, url), timeout=15)
        if r.status_code >= 300:
            log.warning("Teams respondeu %s: %s", r.status_code, r.text[:200])
            return False, f"O Teams respondeu HTTP {r.status_code}."
        return True, "ok"
    except httpx.HTTPError as e:
        log.warning("Falha ao enviar alerta: %s", e)
        return False, f"Falha de conexão com o Teams: {e}"
