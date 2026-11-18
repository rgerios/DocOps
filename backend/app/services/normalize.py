"""Converte qualquer arquivo aceito (coletor v2, bundle, DocViva v1, inventário de VPC legado) em payloads docviva/2."""
import gzip
import json
import re

REGION_RE = re.compile(r"^[a-z]{2}(-gov)?-[a-z]+-\d$")


def parse_bytes(raw: bytes) -> object:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _from_filename(name: str) -> tuple[str, str | None]:
    base = re.sub(r"\.json(\.gz)?$", "", name or "", flags=re.I)
    m = re.search(r"(\d{12})", base)
    alias = re.sub(r"[_-]?\d{12}.*$", "", re.sub(r"^docviva_?", "", base)).strip("_-")
    return alias or (m.group(1) if m else base), (m.group(1) if m else None)


def _legacy(account_id: str, alias: str, collected_at, version: str, regions: dict, glob: dict | None = None) -> dict:
    return {"schema": "docviva/2", "collector_version": version, "collected_at": collected_at, "legacy": True,
            "account": {"id": account_id, "alias": alias, "legacy": True, "iam_aliases": [],
                        "regions_scanned": sorted(regions), "regions_with_resources": sorted(regions)},
            "global": glob or {}, "regions": regions, "regions_security": {}, "errors": []}


def to_payloads(obj, filename: str = "") -> list[dict]:
    if not isinstance(obj, dict):
        raise ValueError("JSON inválido")
    schema = obj.get("schema")
    if schema == "docviva/2":
        return [obj]
    if schema == "docviva-bundle/2":
        return [a for a in obj.get("accounts", []) if a.get("schema") == "docviva/2"]
    if schema == "docviva-workspace/2":
        raise ValueError("Workspace do DocViva: importe os arquivos do coletor (o workspace é para o DocViva offline).")
    accs = obj.get("accounts")
    if isinstance(accs, dict):  # DocViva v1
        out = []
        for alias, a in accs.items():
            regs = {}
            for r, d in (a.get("regions") or {}).items():
                d = dict(d)
                d["load_balancers"] = d.pop("elb", None) or d.get("load_balancers") or []
                regs[r] = d
            glob = {"s3": a.get("s3") or [], "route53": {"zones": [{**z, "name": (z.get("name") or "").rstrip(".")} for z in a.get("route53") or []]}}
            out.append(_legacy(str(a.get("account_id") or alias), alias, obj.get("collected_at"), "v1", regs, glob))
        return out
    region_keys = [k for k in obj if REGION_RE.match(k)]
    if region_keys:  # inventário de VPC legado
        alias, acc = _from_filename(filename)
        for r in region_keys:
            for v in obj.get(r) or []:
                acc = acc or v.get("owner")
        regs = {r: {"vpcs": obj[r]} for r in region_keys if obj.get(r)}
        return [_legacy(acc or alias, alias, None, "vpc-v1", regs)]
    raise ValueError("Formato não reconhecido")
