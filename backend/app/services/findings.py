"""Motor de achados — porte fiel do motor do DocViva (viewer).

Os IDs dos achados são calculados com o mesmo hash FNV-1a do viewer, então a tratativa registrada
na tela (nota 'finding|<id>') vale para o mesmo achado aqui (alertas, relatórios, contadores).
Se alterar um título aqui, altere igual em frontend/public/viewer/index.html.
"""
import math
import re
from datetime import datetime, timezone

RULES = {
    "sensitive_ports": [21, 22, 23, 25, 445, 1433, 1521, 2049, 2375, 3306, 3389, 5432, 5601, 5900, 6379, 9200, 9300, 11211, 27017],
    "deprecated_runtimes": re.compile(r"^(python2\.7|python3\.[6-9]$|nodejs(4\.3|6\.10|8\.10|10\.x|12\.x|14\.x|16\.x|18\.x)$|dotnetcore|dotnet5|dotnet6|ruby2\.|ruby3\.2|java8$|go1\.x|provided$)"),
    "eks_min_standard": "1.34",
    "key_max_age_days": 90,
    "stopped_days": 30,
    "cert_critical_days": 30,
    "cert_warn_days": 60,
    "subnet_low_free_pct": 10,
    "stale_days": 30,
}
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
SEV_LABEL = {"critical": "Crítico", "high": "Alto", "medium": "Médio", "low": "Baixo", "info": "Info"}


# ── utilidades idênticas às do viewer ────────────────────────────────────────
def js_hash(s: str) -> str:
    h = 2166136261
    b = s.encode("utf-16-le")
    for i in range(0, len(b), 2):
        h ^= b[i] | (b[i + 1] << 8)
        h = (h * 16777619) & 0xFFFFFFFF
    return _b36(h)


def _b36(n: int) -> str:
    if n == 0:
        return "0"
    d = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = d[r] + out
    return out


def _js(v) -> str:
    return "" if v is None else str(v)


def parse_dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def days(s):
    d = parse_dt(s)
    return None if not d else math.floor((datetime.now(timezone.utc) - d).total_seconds() / 86400)


def fmt_d(s):
    d = parse_dt(s)
    return d.strftime("%d/%m/%Y") if d else (s or "—")


def ip2n(ip):
    p = str(ip).split(".")
    if len(p) != 4:
        return None
    try:
        v = [int(x) for x in p]
    except ValueError:
        return None
    if any(x < 0 or x > 255 for x in v):
        return None
    return (v[0] << 24) + (v[1] << 16) + (v[2] << 8) + v[3]


def n2ip(n):
    return ".".join(str((n >> s) & 255) for s in (24, 16, 8, 0))


def cidr(c):
    if not c or not isinstance(c, str) or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+/\d+", c.strip()):
        return None
    ip, p = c.strip().split("/")
    pre = int(p)
    n = ip2n(ip)
    if n is None or pre < 0 or pre > 32:
        return None
    size = 2 ** (32 - pre)
    s = (n // size) * size
    return {"s": s, "e": s + size - 1, "p": pre, "size": size, "net": f"{n2ip(s)}/{pre}"}


def overlaps(a, b):
    return a["s"] <= b["e"] and b["s"] <= a["e"]


def cmp_ver(a, b):
    def nums(x):
        out = []
        for p in str(x).split("."):
            try:
                out.append(int(p))
            except ValueError:
                out.append(0)
        return out
    x, y = nums(a), nums(b)
    for i in range(max(len(x), len(y))):
        d = (x[i] if i < len(x) else 0) - (y[i] if i < len(y) else 0)
        if d:
            return d
    return 0


def ttype(t):
    t = str(t or "")
    for p, n in (("igw-", "igw"), ("nat-", "nat"), ("tgw-", "tgw"), ("pcx-", "peering"), ("vgw-", "vgw"), ("eni-", "eni"), ("vpce-", "endpoint")):
        if t.startswith(p):
            return n
    return "local" if t == "local" else "other"


# ── índice (igual ao rebuild() do viewer) ────────────────────────────────────
SIMPLE = {"ec2": "ec2", "ebs": "ebs_volumes", "eip": "eips", "ami": "amis", "asg": "asg", "beanstalk": "beanstalk", "ssm": "ssm_managed",
          "tgw": "transit_gateways", "vpn": "vpn_connections", "vgw": "vpn_gateways", "cgw": "customer_gateways", "dx": "dx_connections",
          "vif": "dx_vifs", "resolver": "resolver_endpoints", "rrule": "resolver_rules", "cvpn": "client_vpn", "lb": "load_balancers",
          "tg": "target_groups", "lambda": "lambda", "apigw": "api_gateway", "sqs": "sqs", "sns": "sns", "sfn": "step_functions",
          "ecs": "ecs", "eks": "eks", "ecr": "ecr", "rds": "rds", "aurora": "rds_clusters", "ddb": "dynamodb", "cache": "elasticache",
          "os": "opensearch", "efs": "efs", "fsx": "fsx", "redshift": "redshift", "mq": "mq", "msk": "msk", "acm": "acm", "kms": "kms",
          "secret": "secrets", "trail": "cloudtrail", "waf": "waf", "alarm": "cloudwatch_alarms", "loggroup": "log_groups"}


def effective_tiers(v):
    rts = v.get("route_tables") or []
    main = next((rt for rt in rts if rt.get("main") or "main" in (rt.get("assocs") or [])), None)
    by_s = {}
    for rt in rts:
        for a in rt.get("assocs") or []:
            if a and str(a).startswith("subnet-"):
                by_s[a] = rt
    for s in v.get("subnets") or []:
        if s.get("tier"):
            continue
        rt = by_s.get(s.get("id")) or main
        s["route_table"] = s.get("route_table") or (rt or {}).get("id")
        default = [r for r in (rt or {}).get("routes") or [] if r.get("dest") == "0.0.0.0/0" and r.get("state") != "blackhole"]
        igw = next((r for r in default if str(r.get("target")).startswith("igw-")), None)
        if igw:
            s["tier"], s["egress"] = "public", igw["target"]
        elif default:
            s["tier"], s["egress"] = "private", default[0]["target"]
        else:
            s["tier"] = "isolated"
        s["public"] = s["tier"] == "public"


class Inventory:
    def __init__(self, payloads: list[dict]):
        self.accounts = []
        self.db: dict[str, list] = {}
        self.vpc_name = {}
        for p in payloads:
            acc = p.get("account") or {}
            self.accounts.append({"id": acc.get("id"), "alias": acc.get("alias") or acc.get("id"), "collected_at": p.get("collected_at"),
                                  "legacy": bool(p.get("legacy") or acc.get("legacy")), "global": p.get("global") or {},
                                  "regions": p.get("regions") or {}, "regions_security": p.get("regions_security") or {}})
        self.accounts.sort(key=lambda a: str(a["alias"]))
        self._build()
        self._nets()

    def push(self, k, row):
        self.db.setdefault(k, []).append(row)

    def rows(self, k):
        return self.db.get(k, [])

    def acct(self, aid):
        return next((a for a in self.accounts if a["id"] == aid), None)

    def alias(self, aid):
        a = self.acct(aid)
        return a["alias"] if a else aid

    def _build(self):
        for a in self.accounts:
            A = a["id"]
            for r, d in a["regions"].items():
                base = {"_a": A, "_r": r}
                for v in d.get("vpcs") or []:
                    effective_tiers(v)
                    self.vpc_name[f"{A}|{v.get('vpc_id')}"] = v.get("name")
                    df = bool(v.get("is_default"))
                    self.push("vpc", {**v, **base, "_def": df})
                    for s in v.get("subnets") or []:
                        self.push("subnet", {**s, "vpc_id": v.get("vpc_id"), **base, "_def": df})
                    for rt in v.get("route_tables") or []:
                        for ro in rt.get("routes") or []:
                            self.push("route", {"rt_id": rt.get("id"), "rt_name": rt.get("name"), "main": bool(rt.get("main") or "main" in (rt.get("assocs") or [])),
                                                "vpc_id": v.get("vpc_id"), **ro, "target_type": ro.get("target_type") or ttype(ro.get("target")), **base, "_def": df})
                    for n in v.get("nat_gws") or []:
                        self.push("nat", {**n, "vpc_id": v.get("vpc_id"), **base})
                for g in d.get("security_groups") or []:
                    v = next((x for x in d.get("vpcs") or [] if x.get("vpc_id") == g.get("vpc_id")), None)
                    self.push("sg", {**g, **base, "_def": bool(v and v.get("is_default"))})
                for k, src in SIMPLE.items():
                    for x in d.get(src) or []:
                        self.push(k, {**x, **base})
                for x in (d.get("backup") or {}).get("plans") or []:
                    self.push("bplan", {**x, **base})
            g = a["global"]
            for b in g.get("s3") or []:
                self.push("s3", {**b, "_a": A, "_r": b.get("region") or "global"})
            for c in g.get("cloudfront") or []:
                self.push("cf", {**c, "_a": A, "_r": "global"})
            for w in g.get("waf_cloudfront") or []:
                self.push("waf", {**w, "_a": A, "_r": "global"})
            for u in (g.get("iam") or {}).get("users") or []:
                self.push("user", {**u, "_a": A, "_r": "global"})

    def _nets(self):
        self.nets, self.ovl = [], []
        for v in self.rows("vpc"):
            if v.get("is_default"):
                continue
            for i, c in enumerate([v.get("cidr"), *(v.get("extra_cidrs") or [])]):
                x = cidr(c)
                if x:
                    self.nets.append({**x, "cidr": c, "kind": "secundário" if i else "primário", "vpc_id": v.get("vpc_id"), "vpc": v.get("name"),
                                      "_a": v["_a"], "_r": v["_r"]})
        for i in range(len(self.nets)):
            for j in range(i + 1, len(self.nets)):
                a, b = self.nets[i], self.nets[j]
                if a["vpc_id"] == b["vpc_id"] and a["_a"] == b["_a"]:
                    continue
                if overlaps(a, b):
                    self.ovl.append((a, b))


# ── achados ──────────────────────────────────────────────────────────────────
def compute(payloads: list[dict]) -> list[dict]:
    inv = Inventory(payloads)
    out = []

    def F(sev, cat, title, row, typ, rec, detail=""):
        if row:
            rid = row.get("vpc_id") if (row.get("vpc_id") and typ == "vpc") else (row.get("id") or row.get("name") or row.get("arn") or row.get("domain") or "")
        else:
            rid = ""
        fid = js_hash("|".join([title, typ, _js((row or {}).get("_a")), _js((row or {}).get("_r")), _js(rid)]))
        name = (row or {}).get("name")
        out.append({"id": fid, "sev": sev, "cat": cat, "title": title, "detail": detail, "rec": rec, "type": typ,
                    "account_id": (row or {}).get("_a"), "account": inv.alias((row or {}).get("_a")), "region": (row or {}).get("_r"),
                    "resource": name if name and name != "—" else _js(rid), "resource_id": _js(rid)})

    al = inv.alias
    # rede
    pairs = {}
    for a, b in inv.ovl:
        k = "~".join(sorted([a["_a"] + str(a["vpc_id"]), b["_a"] + str(b["vpc_id"])]))
        pairs.setdefault(k, {"a": a, "b": b, "list": []})["list"].append(f"{a['cidr']} ↔ {b['cidr']}")
    for p in pairs.values():
        a, b = p["a"], p["b"]
        F("high", "Rede", "Sobreposição de CIDR entre VPCs", {"_a": a["_a"], "_r": a["_r"], "vpc_id": a["vpc_id"], "name": a["vpc"], "id": a["vpc_id"]}, "vpc",
          "Renumere uma das VPCs ou garanta que elas nunca precisem se comunicar (peering, TGW, VPN). Reserve blocos exclusivos no plano de IP.",
          f"{a['vpc']} ({al(a['_a'])}/{a['_r']}) × {b['vpc']} ({al(b['_a'])}/{b['_r']}): {', '.join(p['list'])}"
          + (" · entre contas" if a["_a"] != b["_a"] else "") + (" · entre regiões" if a["_r"] != b["_r"] else ""))
    for v in inv.rows("vpc"):
        if v.get("is_default") and not (v.get("enis") or 0) > 0:
            continue
        if not v.get("flow_logs"):
            F("medium", "Segurança", "VPC sem Flow Logs", v, "vpc", "Habilite VPC Flow Logs (CloudWatch Logs ou S3) para investigação de incidentes e auditoria de tráfego.")
        az_priv = {s.get("az") for s in v.get("subnets") or [] if s.get("tier") == "private"}
        nats = [n for n in v.get("nat_gws") or [] if n.get("state") != "failed"]
        if len(az_priv) >= 2 and len(nats) == 1:
            F("low", "Resiliência", "NAT Gateway único para sub-redes privadas em várias AZs", v, "vpc",
              "Uma falha na AZ do NAT interrompe a saída à internet das demais AZs. Avalie um NAT por AZ em produção.",
              f"{len(az_priv)} AZs privadas, NAT em {nats[0].get('az') or nats[0].get('subnet')}")
        for s in v.get("subnets") or []:
            c = cidr(s.get("cidr"))
            tot = s.get("total_ips") or (c["size"] - 5 if c else 0)
            if tot > 0 and s.get("free_ips") is not None and s["free_ips"] / tot * 100 < RULES["subnet_low_free_pct"]:
                F("medium", "Capacidade", "Sub-rede com poucos IPs livres", {**s, "_a": v["_a"], "_r": v["_r"]}, "subnet",
                  "Planeje expansão (CIDR secundário/nova sub-rede) antes que novos ENIs, tasks ou Lambdas falhem por falta de IP.",
                  f"{s.get('cidr')} · {s['free_ips']} de {tot} livres")
    bh = {}
    for r in inv.rows("route"):
        if r.get("state") == "blackhole" and not r.get("_def"):
            bh.setdefault(r["_a"] + "|" + str(r["rt_id"]), {**r, "list": []})["list"].append(f"{r.get('dest')} → {r.get('target')}")
    for r in bh.values():
        F("low", "Rede", "Rotas em blackhole", {**r, "id": r["rt_id"], "name": r.get("rt_name")}, "route",
          "Remova rotas cujo destino não existe mais (peering/gateway excluído) para evitar descarte silencioso de tráfego.", " · ".join(r["list"]))
    for g in inv.rows("sg"):
        if g.get("_def") and not g.get("attached"):
            continue
        for o in g.get("open_world") or []:
            port = str(o.get("port", ""))
            fr, to = o.get("from"), o.get("to")
            is_all = port == "all" or port.endswith(":all") or (fr == 0 and to == 65535)
            sens = is_all or any(fr is not None and to is not None and fr <= p <= to for p in RULES["sensitive_ports"])
            web = fr == to and fr in (80, 443)
            if web:
                continue
            sev = "low" if not g.get("attached") else "critical" if is_all else "high" if sens else "medium"
            title = ("Security Group liberado para toda a internet (todas as portas)" if is_all
                     else "Porta sensível aberta para a internet" if sens else "Porta aberta para a internet")
            F(sev, "Segurança", title, g, "sg", "Restrinja a origem a faixas conhecidas, use SSM Session Manager no lugar de SSH/RDP e coloque serviços atrás de LB/WAF.",
              f"{port} ← 0.0.0.0/0 · {g.get('attached') or 0} interface(s) usando")
    for v in inv.rows("vpn"):
        t = v.get("tunnels") or []
        if not t:
            continue
        down = len([x for x in t if x.get("status") != "UP"])
        det = " · ".join(f"{x.get('outside_ip')}: {x.get('status')}" for x in t)
        if down == len(t):
            F("high", "Resiliência", "VPN Site-to-Site sem túneis ativos", v, "vpn", "Verifique o equipamento on-premises, IKE/IPsec e a rota BGP/estática. Sem túneis UP, a conectividade híbrida está fora.", det)
        elif down:
            F("medium", "Resiliência", "VPN com túnel redundante fora", v, "vpn", "Ative o segundo túnel no equipamento on-premises para ter redundância durante manutenções da AWS.", det)
    # compute
    for i in inv.rows("ec2"):
        if i.get("imds_v2") is False and i.get("state") == "running":
            F("medium", "Segurança", "EC2 aceita IMDSv1", i, "ec2", "Exija IMDSv2 (HttpTokens=required) para mitigar roubo de credenciais via SSRF.")
        sd = days(i.get("stopped_since")) if i.get("stopped_since") else None
        if i.get("state") == "stopped" and sd is not None and sd > RULES["stopped_days"]:
            F("low", "Custo", "Instância parada há muito tempo", i, "ec2", "Instâncias paradas ainda cobram EBS. Gere AMI/snapshot e encerre, ou documente o motivo.",
              f"parada desde {fmt_d(i.get('stopped_since'))} ({sd} dias)")
        if i.get("state") == "running" and i.get("ssm") and i.get("ssm") != "Online":
            F("low", "Operação", "Instância fora do SSM", i, "ec2", "Instale/atualize o SSM Agent e anexe um instance profile com AmazonSSMManagedInstanceCore para acesso e patching sem portas abertas.", f"status SSM: {i.get('ssm')}")
        if i.get("public_ip") and i.get("state") == "running":
            F("info", "Exposição", "Instância com IP público", i, "ec2", "Confirme se a exposição direta é necessária; prefira LB/NAT e acesso via SSM.", i.get("public_ip"))
        if i.get("state") == "running" and str(i.get("type") or "").startswith(("t2.", "m4.", "c4.", "r4.")):
            F("low", "Custo", "[COST06] EC2 em geração antiga", i, "ec2",
              "Avalie migrar para gerações atuais (t3/t3a, m6i/m7i, c6i, r6i) ou Graviton (t4g/m7g) para melhor custo-benefício.",
              str(i.get("type")))
    for v in inv.rows("ebs"):
        if v.get("encrypted") is False:
            F("medium", "Segurança", "Volume EBS sem criptografia", v, "ebs", "Habilite \"EBS encryption by default\" na região e migre o volume via snapshot criptografado.")
        if v.get("state") == "available":
            F("low", "Custo", "Volume EBS não anexado", v, "ebs", "Volume órfão gera custo contínuo. Faça snapshot e exclua se não houver uso.", f"{v.get('size_gb')} GB {v.get('type')}")
        if v.get("type") == "gp2":
            F("low", "Custo", "[COST06] Volume EBS gp2 (migrar para gp3)", v, "ebs",
              "Volumes gp3 custam ~20% menos por GB que gp2 e já entregam 3.000 IOPS sem downtime na conversão.",
              f"{v.get('size_gb')} GB gp2")
    for e in inv.rows("eip"):
        if not e.get("associated"):
            F("low", "Custo", "IP elástico sem associação", {**e, "id": e.get("allocation_id") or e.get("ip")}, "eip", "IPs públicos IPv4 são cobrados por hora. Libere os que não estão em uso.", e.get("ip") or "")
    # dados
    prd = re.compile(r"pr[do]d|prod", re.I)
    for d in inv.rows("rds"):
        if d.get("publicly_accessible"):
            F("high", "Segurança", "RDS acessível publicamente", d, "rds", "Desative PubliclyAccessible e acesse via rede privada (VPN, bastion SSM ou TGW).", d.get("endpoint") or "")
        if d.get("encrypted") is False:
            F("medium", "Segurança", "RDS sem criptografia em repouso", d, "rds", "Recrie a instância a partir de snapshot copiado com criptografia KMS.")
        if d.get("backup_retention") == 0:
            F("high", "Resiliência", "RDS sem backup automático", d, "rds", "Defina retenção de backup (≥7 dias) e/ou inclua no AWS Backup.")
        if d.get("multi_az") is False and not d.get("cluster") and prd.search(str(d.get("id"))):
            F("medium", "Resiliência", "RDS de produção sem Multi-AZ", d, "rds", "Habilite Multi-AZ para failover automático em falha de AZ.")
        if d.get("deletion_protection") is False and prd.search(str(d.get("id"))):
            F("low", "Resiliência", "RDS de produção sem proteção contra exclusão", d, "rds", "Ative DeletionProtection.")
        if str(d.get("class") or "").startswith(("db.t2.", "db.m4.", "db.r4.")):
            F("low", "Custo", "[COST06] RDS em geração antiga", d, "rds",
              "Avalie atualizar para classes atuais (db.t3/db.t4g/db.m6g/db.r6g) com maior performance por dólar.",
              str(d.get("class")))
    for c in inv.rows("aurora"):
        if c.get("encrypted") is False:
            F("medium", "Segurança", "Cluster de banco sem criptografia", c, "aurora", "Restaure a partir de snapshot com criptografia KMS.")
        if c.get("deletion_protection") is False and prd.search(str(c.get("id"))):
            F("low", "Resiliência", "Cluster de produção sem proteção contra exclusão", c, "aurora", "Ative DeletionProtection.")
    for t in inv.rows("ddb"):
        if t.get("pitr") is False:
            F("low", "Resiliência", "DynamoDB sem PITR", t, "ddb", "Ative Point-in-Time Recovery para restaurar a qualquer segundo dos últimos 35 dias.")
    for c in inv.rows("cache"):
        if c.get("encrypted_rest") is False or c.get("encrypted_transit") is False:
            F("medium", "Segurança", "ElastiCache sem criptografia completa", c, "cache", "Habilite criptografia em repouso e em trânsito (requer recriação do cluster).",
              f"repouso: {'sim' if c.get('encrypted_rest') else 'não'} · trânsito: {'sim' if c.get('encrypted_transit') else 'não'}")
    for b in inv.rows("s3"):
        acct_pab = ((inv.acct(b["_a"]) or {}).get("global") or {}).get("s3_account_public_block")
        if b.get("policy_public"):
            F("critical", "Segurança", "Bucket S3 público por política", b, "s3", "Revise a bucket policy. Se o conteúdo precisa ser público, sirva via CloudFront com OAC.")
        elif b.get("public_access_blocked") is False and not acct_pab:
            F("medium", "Segurança", "Bucket S3 sem Block Public Access", b, "s3", "Ative o Block Public Access no bucket ou, melhor, no nível da conta.")
        if b.get("lifecycle") is False:
            F("low", "Custo", "[COST07] Bucket S3 sem política de Lifecycle", b, "s3",
              "Configure regras de Lifecycle (Intelligent-Tiering, Glacier ou expiração de versões antigas) para evitar custo contínuo em S3 Standard.",
              f"{b.get('size_gb', 0)} GB")
    # serverless / containers
    for f in inv.rows("lambda"):
        if f.get("runtime") and RULES["deprecated_runtimes"].search(str(f["runtime"])):
            F("medium", "Operação", "Lambda com runtime descontinuado", f, "lambda", "Atualize para um runtime suportado; runtimes descontinuados não recebem patches de segurança e bloqueiam atualizações da função.", f["runtime"])
    for c in inv.rows("eks"):
        if c.get("version") and cmp_ver(c["version"], RULES["eks_min_standard"]) < 0:
            F("medium", "Operação", "EKS fora do suporte padrão", c, "eks", f"Planeje upgrade (mínimo de referência {RULES['eks_min_standard']}). Suporte estendido tem custo adicional por hora de cluster.", f"versão {c['version']}")
        if c.get("public_access") and "0.0.0.0/0" in (c.get("public_cidrs") or []):
            F("medium", "Segurança", "Endpoint do EKS público para toda a internet", c, "eks", "Restrinja publicAccessCidrs ou use endpoint apenas privado.")
    for r in inv.rows("ecr"):
        if r.get("scan_on_push") is False:
            F("low", "Segurança", "ECR sem scan de imagens", r, "ecr", "Ative scan on push (ou Inspector enhanced scanning) para detectar CVEs.")
        if r.get("lifecycle_policy") is False and (r.get("image_count") or 0) > 50:
            F("low", "Custo", "ECR sem lifecycle policy", r, "ecr", "Crie regra para expirar imagens antigas/untagged.", f"{r.get('image_count')} imagens · {r.get('size_mb')} MB")
    # borda
    for c in inv.rows("acm"):
        if not c.get("expires"):
            continue
        dd = days(c["expires"])
        if dd is None:
            continue
        left = -dd
        used = (c.get("in_use") or 0) > 0
        if left < 0:
            F("critical" if used else "low", "Operação", "Certificado expirado", c, "acm", "Renove/importe imediatamente — está em uso." if used else "Remova o certificado expirado sem uso.", f"expirou em {fmt_d(c['expires'])}")
        elif left < RULES["cert_critical_days"] and used:
            F("medium" if (c.get("type") == "AMAZON_ISSUED" and c.get("renewal") == "ELIGIBLE") else "high", "Operação", "Certificado vence em menos de 30 dias", c, "acm",
              "Certificado importado não renova sozinho: providencie renovação e reimporte." if c.get("type") == "IMPORTED" else "Confirme que a validação DNS está ativa para a renovação automática.",
              f"{left} dias · {fmt_d(c['expires'])}")
        elif left < RULES["cert_warn_days"] and used and c.get("type") == "IMPORTED":
            F("medium", "Operação", "Certificado importado vence em menos de 60 dias", c, "acm", "Agende a renovação.", f"{left} dias")
    waf_albs = {f"{w['_a']}|{x}" for w in inv.rows("waf") for x in w.get("albs") or []}
    for lb in inv.rows("lb"):
        if lb.get("scheme") != "internet-facing":
            continue
        ls = lb.get("listeners") or []
        https = any(l.get("protocol") in ("HTTPS", "TLS", "SSL") for l in ls)
        http = [l for l in ls if l.get("protocol") == "HTTP"]
        if lb.get("type") == "application" and http and not https:
            F("medium", "Segurança", "ALB público sem HTTPS", lb, "lb", "Adicione listener HTTPS com certificado ACM e redirecione HTTP→HTTPS.")
        if lb.get("type") == "application" and f"{lb['_a']}|{lb.get('name')}" not in waf_albs and not lb.get("legacy") and lb.get("arn"):
            F("low", "Segurança", "ALB público sem WAF", lb, "lb", "Associe um Web ACL (AWS WAF) com regras gerenciadas (Core rule set, IP reputation).")
    for t in inv.rows("tg"):
        if (t.get("unhealthy") or 0) > 0:
            F("medium", "Operação", "Target group com alvos não saudáveis", t, "tg", "Verifique health check, security groups e a aplicação nos alvos.", f"{t['unhealthy']} de {t.get('targets')} não saudáveis")
    for c in inv.rows("cf"):
        if c.get("viewer_protocol") == "allow-all":
            F("low", "Segurança", "CloudFront aceita HTTP sem redirecionar", c, "cf", "Use redirect-to-https no comportamento padrão.")
        if c.get("min_tls") and re.search(r"TLSv1(_2016)?$|SSLv3|TLSv1\.1", str(c["min_tls"])):
            F("medium", "Segurança", "CloudFront com TLS mínimo antigo", c, "cf", "Use TLSv1.2_2021 ou superior.", c["min_tls"])
    # segurança da conta
    for a in inv.accounts:
        if a["legacy"]:
            continue
        ab = {"_a": a["id"], "_r": "global", "id": a["id"], "name": a["alias"]}
        iam = a["global"].get("iam") or {}
        root = iam.get("root")
        if root:
            if root.get("mfa") is False:
                F("critical", "Segurança", "Conta root sem MFA", ab, "account", "Ative MFA (preferencialmente hardware/passkey) no usuário root imediatamente.")
            if root.get("access_keys"):
                F("critical", "Segurança", "Conta root com chaves de acesso ativas", ab, "account", "Remova as access keys do root; use usuários/roles com menor privilégio.")
        if iam.get("account_summary") and not iam.get("password_policy") and any(u.get("console") for u in iam.get("users") or []):
            F("medium", "Segurança", "Sem política de senha da conta", ab, "account", "Defina política de senha (tamanho, complexidade, expiração) ou centralize o acesso no IAM Identity Center.")
        for u in iam.get("users") or []:
            urow = {**u, "_a": a["id"], "_r": "global", "id": u.get("name")}
            if u.get("console") and not u.get("mfa"):
                F("high", "Segurança", "Usuário com console sem MFA", urow, "user", "Exija MFA ou migre o acesso humano para IAM Identity Center (SSO).")
            for k in u.get("access_keys") or []:
                age = k.get("age_days")
                if age is not None and age > RULES["key_max_age_days"]:
                    F("medium", "Segurança", "Access key com mais de 90 dias", urow, "user", "Rotacione a chave ou substitua por role/credencial temporária.",
                      f"{age} dias · último uso: {fmt_d(k['last_used']) if k.get('last_used') else 'nunca'}")
                if not k.get("last_used") and (age or 0) > 30:
                    F("low", "Segurança", "Access key nunca utilizada", urow, "user", "Desative/remova chaves sem uso.")
            if u.get("admin"):
                F("info", "Segurança", "Usuário IAM com AdministratorAccess", urow, "user", "Avalie menor privilégio e acesso administrativo via SSO com sessão temporária.")
        trails = [t for r in a["regions"].values() for t in r.get("cloudtrail") or []]
        if not any(t.get("multi_region") and t.get("logging") for t in trails) and not (a["global"].get("organization") or {}).get("org_trail"):
            F("high", "Segurança", "Sem CloudTrail multi-região ativo", ab, "account", "Crie uma trilha multi-região (ou trilha da Organization) com validação de log e bucket protegido.")
        rs = a["regions_security"]
        used = list(a["regions"].keys())
        gd_off = [r for r in used if rs.get(r) and not rs[r].get("guardduty")]
        if gd_off:
            F("medium", "Segurança", "GuardDuty desativado em regiões com recursos", ab, "account", "Ative o GuardDuty (de preferência via Organization, com administrador delegado) em todas as regiões.", ", ".join(gd_off))
        gd_high = sum(((r.get("guardduty") or {}).get("findings") or {}).get("high", 0) for r in a["regions"].values())
        if gd_high:
            F("high", "Segurança", "GuardDuty com achados de severidade alta abertos", ab, "account", "Investigue e trate os achados no console do GuardDuty.", f"{gd_high} achado(s) alto(s)")
        if used and not any((rs.get(r) or {}).get("securityhub") for r in used):
            F("low", "Governança", "Security Hub não habilitado", ab, "account", "Habilite o Security Hub com o padrão AWS Foundational Security Best Practices.")
        if used and not any((rs.get(r) or {}).get("config") for r in used):
            F("low", "Governança", "AWS Config não habilitado", ab, "account", "Habilite o Config para histórico de configuração e regras de conformidade.")
        has_data = any(x["_a"] == a["id"] for k in ("rds", "efs", "ddb", "ec2") for x in inv.rows(k))
        plans = sum(len((r.get("backup") or {}).get("plans") or []) for r in a["regions"].values())
        if has_data and not plans:
            F("medium", "Resiliência", "Nenhum plano do AWS Backup", ab, "account", "Crie planos de backup centralizados (RDS, EBS, EFS, DynamoDB) com retenção definida e cofre protegido.")
        for r, d in a["regions"].items():
            no_ret = [g for g in d.get("log_groups") or [] if g.get("retention_days") is None]
            if len(no_ret) >= 3:
                F("low", "Custo", "Log groups sem retenção definida", {"_a": a["id"], "_r": r, "id": r, "name": f"{len(no_ret)} log groups"}, "loggroup",
                  "Defina retenção (ex.: 30/90/365 dias) — logs sem expiração crescem e cobram indefinidamente.",
                  f"{len(no_ret)} log groups · {round(sum(g.get('stored_mb') or 0 for g in no_ret))} MB")
            alarming = [x for x in d.get("cloudwatch_alarms") or [] if x.get("state") == "ALARM"]
            if alarming:
                F("info", "Operação", "Alarmes do CloudWatch em estado ALARM", {"_a": a["id"], "_r": r, "id": r, "name": f"{len(alarming)} alarmes"}, "alarm",
                  "Revise se são alarmes reais ou ruído a ajustar.", ", ".join(x.get("name") or "" for x in alarming[:5]))
            snaps = d.get("ebs_snapshots_summary") or {}
            if (snaps.get("older_than_365d") or 0) > 0:
                F("low", "Custo", "[COST07] Snapshots EBS com mais de 1 ano", {"_a": a["id"], "_r": r, "id": r, "name": f"{snaps['older_than_365d']} snapshots"}, "snapshot",
                  "Revise retenção via Data Lifecycle Manager (DLM) ou AWS Backup e remova snapshots obsoletos.",
                  f"{snaps['older_than_365d']} antigo(s) · total {snaps.get('total_gb', 0)} GB")
            for vpc in d.get("vpcs") or []:
                if vpc.get("nat_gws"):
                    has_gw_ep = any("s3" in str(ep.get("service") or "") or "dynamodb" in str(ep.get("service") or "") for ep in (vpc.get("endpoints") or []))
                    if not has_gw_ep:
                        F("low", "Custo", "[COST05] VPC com NAT Gateway sem Gateway Endpoint",
                          {"_a": a["id"], "_r": r, "id": vpc.get("vpc_id"), "name": vpc.get("name") or vpc.get("vpc_id")}, "vpc",
                          "Crie VPC Gateway Endpoints gratuitos para S3 e DynamoDB para evitar cobrança de tráfego por GB no NAT Gateway.",
                          vpc.get("cidr") or "")
        finops = (a.get("global") or {}).get("finops") or {}
        co = finops.get("compute_optimizer") or {}
        for rec in co.get("ec2") or []:
            sav = rec.get("savings_usd") or 0
            F("medium" if sav >= 20 else "low", "Custo", "[COST06] Compute Optimizer: EC2 superdimensionada",
              {"_a": a["id"], "_r": "global", "id": rec.get("id"), "name": rec.get("name") or rec.get("id")}, "ec2",
              f"Avalie redimensionar de {rec.get('current')} para {rec.get('recommended')}.",
              f"{rec.get('current')} -> {rec.get('recommended')} · economia ~US$ {sav}/mês")
        for rec in co.get("ebs") or []:
            sav = rec.get("savings_usd") or 0
            F("medium" if sav >= 20 else "low", "Custo", "[COST06] Compute Optimizer: EBS não otimizado",
              {"_a": a["id"], "_r": "global", "id": rec.get("id"), "name": rec.get("id")}, "ebs",
              f"Ajuste o volume de {rec.get('current')} para {rec.get('recommended')}.",
              f"{rec.get('current')} -> {rec.get('recommended')} · economia ~US$ {sav}/mês")
        for rec in co.get("lambda") or []:
            sav = rec.get("savings_usd") or 0
            F("low", "Custo", "[COST06] Compute Optimizer: Lambda não otimizada",
              {"_a": a["id"], "_r": "global", "id": rec.get("id"), "name": rec.get("id")}, "lambda",
              f"Ajuste a memória de {rec.get('current_mb')} MB para {rec.get('recommended_mb')} MB.",
              f"economia ~US$ {sav}/mês")
        sp = finops.get("savings_plans") or {}
        if (sp.get("estimated_monthly_savings_usd") or 0) >= 10:
            F("medium", "Custo", "[COST08] Oportunidade de Savings Plans", ab, "account",
              f"Avalie {sp.get('type')} com compromisso de US$ {sp.get('hourly_commitment')}/h.",
              f"economia ~US$ {sp.get('estimated_monthly_savings_usd')}/mês ({sp.get('estimated_savings_pct')}%)")
        for wa in finops.get("well_architected") or []:
            sev = "high" if (wa.get("high") or 0) > 0 else "medium"
            F(sev, "Well-Architected", "Workload com riscos no AWS Well-Architected Tool",
              {"_a": a["id"], "_r": "global", "id": f"{wa.get('workload')}|{wa.get('lens')}", "name": wa.get("workload")}, "well_architected",
              "Revise os High/Medium Risk Issues no console do AWS Well-Architected Tool.",
              f"lens {wa.get('lens')} · {wa.get('high', 0)} alto(s), {wa.get('medium', 0)} médio(s)")
        dd = days(a["collected_at"])
        if dd is not None and dd > RULES["stale_days"]:
            F("info", "Governança", "Inventário desatualizado", ab, "account", "Rode o coletor novamente para atualizar a documentação.", f"coletado há {dd} dias")
    for k in inv.rows("kms"):
        if k.get("rotation") is False:
            F("low", "Segurança", "Chave KMS sem rotação automática", {**k, "name": (k.get("aliases") or [None])[0] or k.get("id")}, "kms", "Ative a rotação anual automática da chave.")
    for s in inv.rows("secret"):
        if not s.get("rotation"):
            F("info", "Segurança", "Segredo sem rotação automática", {**s, "id": s.get("name")}, "secret", "Configure rotação com Lambda para credenciais de banco e integrações.")
    out.sort(key=lambda f: (SEV_ORDER[f["sev"]], f["cat"], f["title"]))
    return out
