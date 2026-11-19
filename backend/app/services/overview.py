"""Cálculo do Panorama Geral (Raio-X 8 Pilares + Benchmark/Camadas) e Inventário Unificado de Assets."""
from __future__ import annotations

from typing import Any


def _status_from_score(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 60:
        return "moderate"
    if score >= 40:
        return "suboptimal"
    return "critical"


def _clamp(val: float, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(round(val))))


def _collect_metrics(cols: list[Any], open_findings: list[dict]) -> dict[str, Any]:
    """Extrai contadores reais de cobertura e saúde a partir dos payloads coletados."""
    m = {
        "regions": set(),
        "ec2": 0, "ec2_running": 0, "ec2_old_gen": 0, "ec2_no_imdsv2": 0,
        "ecs": 0, "eks": 0, "lambda": 0, "ecr": 0,
        "s3": 0, "s3_public_block": 0, "s3_lifecycle": 0, "s3_encrypted": 0,
        "ebs": 0, "ebs_gp2": 0, "ebs_unattached": 0, "ebs_encrypted": 0, "efs": 0,
        "rds": 0, "rds_multi_az": 0, "rds_encrypted": 0, "rds_public": 0,
        "dynamodb": 0, "elasticache": 0,
        "vpcs": 0, "vpcs_flow_logs": 0, "albs": 0, "nat_gws": 0, "eips": 0, "eips_unused": 0,
        "route53": 0, "cloudfront": 0, "apigw": 0, "vpns": 0, "tgws": 0,
        "cw_alarms": 0, "log_groups": 0, "log_groups_retention": 0,
        "cloudtrail": 0, "cloudtrail_multi": 0,
        "iam_users": 0, "iam_mfa_users": 0, "iam_root_mfa": False, "iam_pwd_policy": False,
        "kms": 0, "config_enabled": 0, "backup_plans": 0, "org_enabled": False,
        "mtd_cost": 0.0, "forecast_cost": 0.0, "savings_usd": 0.0,
        "has_cost_explorer": False, "has_co": False, "has_sp": False, "wa_risks": 0,
        "waf": 0, "guardduty": 0, "securityhub": 0, "acm": 0, "sgs_open_world": 0,
    }

    for col in cols:
        p = col.payload or {}
        if not p:
            continue
        glob = p.get("global") or {}
        iam = glob.get("iam") or {}
        acc_sum = iam.get("account_summary") or {}
        if acc_sum.get("mfa") or (iam.get("root") or {}).get("mfa"):
            m["iam_root_mfa"] = True
        if iam.get("password_policy"):
            m["iam_pwd_policy"] = True
        for u in iam.get("users") or []:
            m["iam_users"] += 1
            if u.get("mfa"):
                m["iam_mfa_users"] += 1

        if glob.get("organization"):
            m["org_enabled"] = True

        s3_list = glob.get("s3") or []
        m["s3"] += len(s3_list)
        if glob.get("s3_account_public_block"):
            m["s3_public_block"] += 1
        for b in s3_list:
            if b.get("lifecycle") is True:
                m["s3_lifecycle"] += 1
            if b.get("encrypted", True):
                m["s3_encrypted"] += 1

        m["route53"] += len(glob.get("route53") or [])
        m["cloudfront"] += len(glob.get("cloudfront") or [])
        m["waf"] += len(glob.get("waf_cloudfront") or [])

        cost = glob.get("cost") or {}
        if cost.get("mtd") is not None or cost.get("forecast") is not None:
            m["has_cost_explorer"] = True
        m["mtd_cost"] += float(cost.get("mtd") or 0)
        m["forecast_cost"] += float(cost.get("forecast") or 0)

        fin = glob.get("finops") or {}
        co = fin.get("compute_optimizer") or {}
        co_recs = [r for k in ("ec2", "ebs", "lambda") for r in (co.get(k) or [])]
        if co_recs:
            m["has_co"] = True
        sp = fin.get("savings_plans") or {}
        if sp and (sp.get("plans") or sp.get("hourly_commitment") or sp.get("estimated_monthly_savings_usd")):
            m["has_sp"] = True
        m["savings_usd"] += sum(float(r.get("savings_usd") or 0) for r in co_recs) + float(sp.get("estimated_monthly_savings_usd") or 0)
        for w in fin.get("well_architected") or []:
            m["wa_risks"] += int(w.get("high") or 0) + int(w.get("medium") or 0)

        for rname, rdata in (p.get("regions") or {}).items():
            if not isinstance(rdata, dict):
                continue
            has_any = False
            ec2s = rdata.get("ec2") or []
            if ec2s:
                has_any = True
            m["ec2"] += len(ec2s)
            for i in ec2s:
                if i.get("state") == "running":
                    m["ec2_running"] += 1
                if str(i.get("type") or "").startswith(("t2.", "m4.", "c4.", "r4.")):
                    m["ec2_old_gen"] += 1
                if i.get("imds_v2") is False:
                    m["ec2_no_imdsv2"] += 1

            m["ecs"] += len(rdata.get("ecs") or [])
            m["eks"] += len(rdata.get("eks") or [])
            m["lambda"] += len(rdata.get("lambda") or [])
            m["ecr"] += len(rdata.get("ecr") or [])

            ebs_list = rdata.get("ebs_volumes") or []
            m["ebs"] += len(ebs_list)
            for v in ebs_list:
                if v.get("type") == "gp2":
                    m["ebs_gp2"] += 1
                if v.get("state") == "available":
                    m["ebs_unattached"] += 1
                if v.get("encrypted"):
                    m["ebs_encrypted"] += 1
            m["efs"] += len(rdata.get("efs") or [])

            rds_list = rdata.get("rds") or []
            m["rds"] += len(rds_list)
            for d in rds_list:
                if d.get("multi_az"):
                    m["rds_multi_az"] += 1
                if d.get("encrypted"):
                    m["rds_encrypted"] += 1
                if d.get("publicly_accessible"):
                    m["rds_public"] += 1
            m["dynamodb"] += len(rdata.get("dynamodb") or [])
            m["elasticache"] += len(rdata.get("elasticache") or [])

            vpcs = rdata.get("vpcs") or []
            m["vpcs"] += len(vpcs)
            for vpc in vpcs:
                if vpc.get("flow_logs"):
                    m["vpcs_flow_logs"] += 1
                m["nat_gws"] += len(vpc.get("nat_gws") or [])
            m["albs"] += len(rdata.get("albs") or [])
            eips = rdata.get("eips") or []
            m["eips"] += len(eips)
            m["eips_unused"] += sum(1 for e in eips if not e.get("associated"))
            m["apigw"] += len(rdata.get("apigateway") or [])
            m["vpns"] += len(rdata.get("vpns") or [])
            m["tgws"] += len(rdata.get("tgws") or [])

            m["cw_alarms"] += len(rdata.get("cloudwatch_alarms") or [])
            lgs = rdata.get("log_groups") or []
            m["log_groups"] += len(lgs)
            m["log_groups_retention"] += sum(1 for lg in lgs if lg.get("retention_days"))

            trails = rdata.get("cloudtrail") or []
            m["cloudtrail"] += len(trails)
            m["cloudtrail_multi"] += sum(1 for tr in trails if tr.get("multi_region") or tr.get("org_trail"))

            m["kms"] += len(rdata.get("kms") or [])
            if (rdata.get("config") or {}).get("enabled") or (isinstance(rdata.get("config"), list) and len(rdata.get("config")) > 0):
                m["config_enabled"] += 1
            backup = rdata.get("backup") or {}
            if isinstance(backup, dict):
                m["backup_plans"] += len(backup.get("plans") or [])
            elif isinstance(backup, list):
                m["backup_plans"] += len(backup)

            sec = rdata.get("regions_security") or {}
            if sec.get("guardduty") or rdata.get("guardduty"):
                m["guardduty"] += 1
            if sec.get("securityhub") or rdata.get("securityhub"):
                m["securityhub"] += 1
            m["waf"] += len(rdata.get("waf") or [])
            m["acm"] += len(rdata.get("acm") or [])
            for sg in rdata.get("security_groups") or []:
                if sg.get("open_world"):
                    m["sgs_open_world"] += 1

            if has_any or rds_list or vpcs or rdata.get("lambda") or rdata.get("ecs") or rdata.get("eks"):
                m["regions"].add(rname)

    m["open_findings"] = open_findings
    return m


def _findings_for_cats(findings: list[dict], keywords: tuple[str, ...]) -> list[dict]:
    out = []
    for f in findings:
        blob = f"{f.get('cat', '')} {f.get('type', '')} {f.get('title', '')} {f.get('id', '')}".lower()
        if any(k in blob for k in keywords):
            out.append(f)
    return out


def _svc(name: str, count: int, ok_cond: bool = True, warn_cond: bool = False) -> dict:
    if count <= 0:
        return {"name": name, "detected": False, "count": 0, "badge": "Não Detectado", "badgeKind": "idle"}
    if not ok_cond:
        return {"name": name, "detected": True, "count": count, "badge": "Proteção Mínima", "badgeKind": "bad"}
    if warn_cond:
        return {"name": name, "detected": True, "count": count, "badge": "Atenção", "badgeKind": "warn"}
    return {"name": name, "detected": True, "count": count, "badge": "Conforme", "badgeKind": "ok"}


def _build_pillars(m: dict[str, Any]) -> list[dict]:
    open_f = m["open_findings"]

    # 1. Computação & Containers
    f_comp = _findings_for_cats(open_f, ("ec2", "ecs", "eks", "lambda", "imdsv2", "compute"))
    comp_res = m["ec2"] + m["ecs"] + m["eks"] + m["lambda"]
    if comp_res == 0:
        s_comp = 35
    else:
        s_comp = 72 + (10 if (m["ecs"] + m["eks"] + m["lambda"]) > 0 else 0) + (8 if m["ec2_old_gen"] == 0 else 0) + (6 if m["ec2_no_imdsv2"] == 0 else 0) - min(24, len(f_comp) * 3)
    s_comp = _clamp(s_comp)

    # 2. Armazenamento S3 & EBS
    f_stor = _findings_for_cats(open_f, ("s3", "ebs", "snapshot", "efs", "bucket", "storage"))
    stor_res = m["s3"] + m["ebs"] + m["efs"]
    if stor_res == 0:
        s_stor = 40
    else:
        s_stor = 68 + (10 if m["s3_public_block"] > 0 else 0) + (10 if m["ebs_gp2"] == 0 else 0) + (8 if m["ebs_unattached"] == 0 else 0) - min(26, len(f_stor) * 3)
    s_stor = _clamp(s_stor)

    # 3. Bancos de Dados
    f_db = _findings_for_cats(open_f, ("rds", "dynamo", "elasticache", "banco", "database"))
    db_res = m["rds"] + m["dynamodb"] + m["elasticache"]
    if db_res == 0:
        s_db = 45
    else:
        s_db = 74 + (10 if m["rds_public"] == 0 else -12) + (8 if m["rds"] == 0 or m["rds_multi_az"] > 0 else 0) + (6 if m["rds"] == 0 or m["rds_encrypted"] == m["rds"] else 0) - min(22, len(f_db) * 4)
    s_db = _clamp(s_db)

    # 4. Redes & Conectividade
    f_net = _findings_for_cats(open_f, ("vpc", "rede", "network", "sg", "security group", "alb", "nat", "vpn", "eip", "route53"))
    net_res = m["vpcs"] + m["albs"] + m["route53"] + m["cloudfront"] + m["vpns"] + m["tgws"]
    if net_res == 0:
        s_net = 40
    else:
        s_net = 72 + (10 if m["vpcs_flow_logs"] > 0 else -6) + (8 if m["albs"] > 0 or m["cloudfront"] > 0 else 0) - min(25, m["sgs_open_world"] * 4 + len(f_net) * 2)
    s_net = _clamp(s_net)

    # 5. Observabilidade & Logs
    f_obs = _findings_for_cats(open_f, ("cloudwatch", "cloudtrail", "log", "flow", "observab", "monitor"))
    obs_res = m["cw_alarms"] + m["log_groups"] + m["cloudtrail"]
    s_obs = 22
    if m["cloudtrail"] > 0:
        s_obs += 26 + (10 if m["cloudtrail_multi"] > 0 else 0)
    if m["log_groups"] > 0:
        s_obs += 16 + (8 if m["log_groups_retention"] > 0 else 0)
    if m["cw_alarms"] > 0:
        s_obs += 14
    if m["vpcs_flow_logs"] > 0:
        s_obs += 6
    s_obs = _clamp(s_obs - min(20, len(f_obs) * 3))

    # 6. Governança & IAM
    f_gov = _findings_for_cats(open_f, ("iam", "kms", "mfa", "root", "config", "backup", "governan", "access key"))
    gov_res = m["iam_users"] + m["kms"] + m["backup_plans"] + m["config_enabled"]
    s_gov = 30
    if m["iam_root_mfa"]:
        s_gov += 16
    if m["iam_pwd_policy"]:
        s_gov += 10
    if m["iam_users"] == 0 or (m["iam_mfa_users"] / max(1, m["iam_users"])) >= 0.8:
        s_gov += 14
    if m["kms"] > 0:
        s_gov += 10
    if m["config_enabled"] > 0:
        s_gov += 10
    if m["backup_plans"] > 0:
        s_gov += 10
    s_gov = _clamp(s_gov - min(28, len(f_gov) * 4))

    # 7. FinOps & Savings
    f_fin = _findings_for_cats(open_f, ("custo", "cost", "finops", "savings", "gp2", "órfã", "orfa", "ocioso", "well-architected"))
    s_fin = 28
    if m["has_cost_explorer"]:
        s_fin += 18
    if m["has_co"]:
        s_fin += 14
    if m["has_sp"]:
        s_fin += 18
    if m["ebs_gp2"] == 0 and m["ebs"] > 0:
        s_fin += 10
    if m["ebs_unattached"] == 0 and m["eips_unused"] == 0:
        s_fin += 8
    s_fin = _clamp(s_fin - min(32, len(f_fin) * 3 + m["wa_risks"] * 2))

    # 8. Segurança Perimetral & Borda
    f_sec = _findings_for_cats(open_f, ("waf", "shield", "guardduty", "securityhub", "security hub", "seguran", "tls", "ssl", "public"))
    sec_res = m["waf"] + m["guardduty"] + m["securityhub"] + m["acm"]
    s_sec = 18
    if m["waf"] > 0:
        s_sec += 24
    if m["guardduty"] > 0:
        s_sec += 22
    if m["securityhub"] > 0:
        s_sec += 20
    if m["acm"] > 0:
        s_sec += 10
    if m["sgs_open_world"] == 0:
        s_sec += 6
    s_sec = _clamp(s_sec - min(28, len(f_sec) * 3))

    def _recs(flist: list[dict], fallbacks: list[tuple[str, str, str, str]]) -> list[dict]:
        items = []
        for f in flist[:3]:
            items.append({
                "title": f.get("title") or "Revisar achado aberto",
                "sev": f.get("sev") or "medium",
                "detail": f.get("rec") or f.get("detail") or "",
                "action": "Analisar com IA",
                "targetRoute": "ia",
            })
        for title, sev, detail, route in fallbacks:
            if len(items) >= 3:
                break
            items.append({"title": title, "sev": sev, "detail": detail, "action": "Abrir módulo", "targetRoute": route})
        return items

    pillars = [
        {
            "id": "compute",
            "name": "Computação & Containers",
            "shortName": "Computação",
            "score": s_comp,
            "benchmark": 84,
            "resourceCount": comp_res,
            "openFindings": len(f_comp),
            "services": [
                _svc("EC2", m["ec2"], ok_cond=m["ec2_no_imdsv2"] == 0, warn_cond=m["ec2_old_gen"] > 0),
                _svc("ECS / EKS", m["ecs"] + m["eks"]),
                _svc("Lambda", m["lambda"]),
                _svc("ECR", m["ecr"]),
            ],
            "recommendations": _recs(f_comp, [
                ("Modernizar instâncias antigas (Graviton / t3 / m6i)", "medium", "Migrar gerações t2/m4/c4 para famílias atuais reduz até 20% de custo.", "finops"),
            ]),
        },
        {
            "id": "storage",
            "name": "Armazenamento S3 & EBS",
            "shortName": "Armazenamento",
            "score": s_stor,
            "benchmark": 82,
            "resourceCount": stor_res,
            "openFindings": len(f_stor),
            "services": [
                _svc("S3 Buckets", m["s3"], ok_cond=m["s3_public_block"] > 0 or m["s3"] == 0, warn_cond=m["s3"] > 0 and m["s3_lifecycle"] < m["s3"]),
                _svc("EBS Volumes", m["ebs"], warn_cond=m["ebs_gp2"] > 0 or m["ebs_unattached"] > 0),
                _svc("EFS", m["efs"]),
            ],
            "recommendations": _recs(f_stor, [
                ("Migrar volumes EBS gp2 → gp3", "medium", "Mesma capacidade com menor custo por GB e melhor performance base.", "finops"),
                ("Configurar políticas de Lifecycle no S3", "low", "Mover objetos frios para Intelligent-Tiering ou Glacier.", "finops"),
            ]),
        },
        {
            "id": "database",
            "name": "Bancos de Dados",
            "shortName": "Bancos de Dados",
            "score": s_db,
            "benchmark": 80,
            "resourceCount": db_res,
            "openFindings": len(f_db),
            "services": [
                _svc("RDS", m["rds"], ok_cond=m["rds_public"] == 0, warn_cond=m["rds"] > 0 and m["rds_multi_az"] < m["rds"]),
                _svc("DynamoDB", m["dynamodb"]),
                _svc("ElastiCache", m["elasticache"]),
            ],
            "recommendations": _recs(f_db, [
                ("Validar Multi-AZ e criptografia em repouso no RDS", "high", "Garante alta disponibilidade e conformidade em bancos críticos.", "explorer"),
            ]),
        },
        {
            "id": "network",
            "name": "Redes & Conectividade",
            "shortName": "Redes",
            "score": s_net,
            "benchmark": 78,
            "resourceCount": net_res,
            "openFindings": len(f_net),
            "services": [
                _svc("VPC", m["vpcs"], warn_cond=m["vpcs"] > 0 and m["vpcs_flow_logs"] == 0),
                _svc("ALB / NLB", m["albs"]),
                _svc("Route 53", m["route53"]),
                _svc("CloudFront", m["cloudfront"]),
            ],
            "recommendations": _recs(f_net, [
                ("Revisar Security Groups abertos para 0.0.0.0/0", "high", "Restringir portas administrativas (SSH/RDP/DB) a VPN ou SSM.", "explorer"),
            ]),
        },
        {
            "id": "observability",
            "name": "Observabilidade & Logs",
            "shortName": "Observabilidade",
            "score": s_obs,
            "benchmark": 76,
            "resourceCount": obs_res,
            "openFindings": len(f_obs),
            "services": [
                _svc("CloudTrail", m["cloudtrail"], ok_cond=m["cloudtrail_multi"] > 0, warn_cond=m["cloudtrail_multi"] == 0),
                _svc("CloudWatch Alarms", m["cw_alarms"]),
                _svc("Log Groups", m["log_groups"], warn_cond=m["log_groups"] > 0 and m["log_groups_retention"] < m["log_groups"]),
                _svc("VPC Flow Logs", m["vpcs_flow_logs"]),
            ],
            "recommendations": _recs(f_obs, [
                ("Ativar CloudTrail multi-região e retenção em Log Groups", "medium", "Evita pontos cegos de auditoria e crescimento infinito de custos de logs.", "ia"),
            ]),
        },
        {
            "id": "governance",
            "name": "Governança & IAM",
            "shortName": "Governança",
            "score": s_gov,
            "benchmark": 75,
            "resourceCount": gov_res,
            "openFindings": len(f_gov),
            "services": [
                _svc("IAM / MFA", max(1, m["iam_users"]) if (m["iam_root_mfa"] or m["iam_users"] > 0) else 0, ok_cond=m["iam_root_mfa"], warn_cond=m["iam_users"] > 0 and m["iam_mfa_users"] < m["iam_users"]),
                _svc("KMS", m["kms"]),
                _svc("AWS Config", m["config_enabled"]),
                _svc("AWS Backup", m["backup_plans"]),
            ],
            "recommendations": _recs(f_gov, [
                ("Habilitar AWS Config e planos no AWS Backup", "medium", "Rastreabilidade contínua de conformidade e recuperação de desastres.", "ia"),
            ]),
        },
        {
            "id": "finops",
            "name": "FinOps & Savings",
            "shortName": "FinOps",
            "score": s_fin,
            "benchmark": 74,
            "resourceCount": int(m["has_cost_explorer"]) + int(m["has_co"]) + int(m["has_sp"]),
            "openFindings": len(f_fin),
            "services": [
                _svc("Cost Explorer", 1 if m["has_cost_explorer"] else 0),
                _svc("Compute Optimizer", 1 if m["has_co"] else 0),
                _svc("Savings Plans / RI", 1 if m["has_sp"] else 0),
            ],
            "recommendations": _recs(f_fin, [
                ("Avaliar Savings Plans e rightsizing no Compute Optimizer", "high", "Reduz custo recorrente de EC2/Fargate/Lambda em até 30%.", "finops"),
            ]),
        },
        {
            "id": "security",
            "name": "Segurança Perimetral & Borda",
            "shortName": "Segurança Borda",
            "score": s_sec,
            "benchmark": 78,
            "resourceCount": sec_res,
            "openFindings": len(f_sec),
            "services": [
                _svc("WAF v2", m["waf"]),
                _svc("GuardDuty", m["guardduty"]),
                _svc("Security Hub", m["securityhub"]),
                _svc("ACM (TLS)", m["acm"]),
            ],
            "recommendations": _recs(f_sec, [
                ("Provisionar AWS WAF v2 com Managed Rules", "high", "Protege ALBs e CloudFront contra OWASP Top 10 e bots.", "ia"),
                ("Habilitar GuardDuty e Security Hub", "high", "Detecção contínua de ameaças e postura CIS/AWS Foundational.", "ia"),
            ]),
        },
    ]

    for p in pillars:
        p["delta"] = p["score"] - p["benchmark"]
        p["status"] = _status_from_score(p["score"])
    return pillars


def build_overview(cols: list[Any], findings: list[dict], account_id: str | None = None) -> dict[str, Any]:
    """Monta o payload do Panorama Geral (Raio-X da Conta + Benchmark/Camadas)."""
    open_all = [f for f in findings if f.get("status", "aberto") == "aberto"]

    accounts_index = []
    for col in cols:
        if not col.payload:
            continue
        acc_f = [f for f in open_all if f.get("account") in (col.account_id, col.alias)]
        acc_m = _collect_metrics([col], acc_f)
        acc_p = _build_pillars(acc_m)
        acc_score = _clamp(sum(x["score"] for x in acc_p) / len(acc_p)) if acc_p else 0
        accounts_index.append({
            "accountId": col.account_id,
            "accountAlias": col.alias or col.account_id,
            "overallScore": acc_score,
        })

    if account_id and account_id != "all":
        sel_cols = [c for c in cols if c.account_id == account_id and c.payload]
        sel_alias = sel_cols[0].alias if sel_cols else account_id
        sel_findings = [f for f in open_all if f.get("account") in (account_id, sel_alias)]
        cur_id, cur_alias = account_id, sel_alias
    else:
        sel_cols = [c for c in cols if c.payload]
        sel_findings = open_all
        cur_id = "all" if len(sel_cols) != 1 else sel_cols[0].account_id
        cur_alias = f"Consolidado ({len(sel_cols)} contas)" if len(sel_cols) > 1 else (sel_cols[0].alias if sel_cols else "Sem coleta")

    m = _collect_metrics(sel_cols, sel_findings)
    pillars = _build_pillars(m)
    overall = _clamp(sum(x["score"] for x in pillars) / len(pillars)) if (sel_cols and pillars) else 0
    bench_avg = _clamp(sum(x["benchmark"] for x in pillars) / len(pillars)) if pillars else 78

    total_resources = m["ec2"] + m["ecs"] + m["eks"] + m["lambda"] + m["s3"] + m["ebs"] + m["rds"] + m["dynamodb"] + m["vpcs"] + m["albs"]
    critical_f = sum(1 for f in sel_findings if f.get("sev") in ("critical", "high"))

    # Camadas concêntricas (Núcleo + 3 anéis)
    layers = {
        "core": [
            {"name": "EC2", "count": m["ec2"], "active": m["ec2"] > 0},
            {"name": "S3", "count": m["s3"], "active": m["s3"] > 0},
            {"name": "RDS", "count": m["rds"], "active": m["rds"] > 0},
            {"name": "VPC", "count": m["vpcs"], "active": m["vpcs"] > 0},
            {"name": "EBS", "count": m["ebs"], "active": m["ebs"] > 0},
            {"name": "Lambda", "count": m["lambda"], "active": m["lambda"] > 0},
        ],
        "governance": [
            {"name": "IAM / MFA", "count": m["iam_users"], "active": m["iam_root_mfa"] or m["iam_users"] > 0},
            {"name": "CloudTrail", "count": m["cloudtrail"], "active": m["cloudtrail"] > 0},
            {"name": "KMS", "count": m["kms"], "active": m["kms"] > 0},
            {"name": "CloudWatch", "count": m["cw_alarms"] + m["log_groups"], "active": (m["cw_alarms"] + m["log_groups"]) > 0},
            {"name": "AWS Config", "count": m["config_enabled"], "active": m["config_enabled"] > 0},
            {"name": "FinOps / SP", "count": int(m["has_sp"]) + int(m["has_co"]), "active": m["has_sp"] or m["has_co"]},
        ],
        "ecosystem": [
            {"name": "WAF v2", "count": m["waf"], "active": m["waf"] > 0},
            {"name": "GuardDuty", "count": m["guardduty"], "active": m["guardduty"] > 0},
            {"name": "Security Hub", "count": m["securityhub"], "active": m["securityhub"] > 0},
            {"name": "CloudFront", "count": m["cloudfront"], "active": m["cloudfront"] > 0},
            {"name": "API Gateway", "count": m["apigw"], "active": m["apigw"] > 0},
            {"name": "ECS / EKS", "count": m["ecs"] + m["eks"], "active": (m["ecs"] + m["eks"]) > 0},
        ],
    }

    # Diagnósticos executivos automáticos
    weakest = sorted(pillars, key=lambda x: x["score"])[:2]
    insights = []
    if weakest and sel_cols:
        w0 = weakest[0]
        insights.append({
            "kind": "bad" if w0["score"] < 45 else "warn",
            "title": f"Maior lacuna: {w0['name']} ({w0['score']}/100)",
            "detail": f"{abs(w0['delta'])} pontos abaixo da referência de mercado ({w0['benchmark']}%). Priorize os serviços ausentes ou com proteção mínima neste pilar.",
            "route": "ia",
            "cta": "Gerar plano com IA",
        })
    if m["savings_usd"] > 0 or m["ebs_gp2"] > 0 or m["ebs_unattached"] > 0:
        sav_txt = f"Economia estimada de US$ {round(m['savings_usd'], 2)}/mês" if m["savings_usd"] > 0 else "Oportunidades imediatas de redução de custo"
        insights.append({
            "kind": "ok",
            "title": sav_txt,
            "detail": f"Detectados {m['ebs_gp2']} volume(s) gp2, {m['ebs_unattached']} EBS órfão(s) e {m['ec2_old_gen']} EC2 de geração antiga.",
            "route": "finops",
            "cta": "Abrir FinOps & Custos",
        })
    if critical_f > 0:
        insights.append({
            "kind": "warn",
            "title": f"{critical_f} achado(s) Crítico/Alto em aberto",
            "detail": "Revise e atribua responsáveis no Explorer ou peça um roteiro priorizado na aba IA Analisando.",
            "route": "explorer",
            "cta": "Ver no Explorer",
        })

    # ── Perfil de Uso & Serviços (sem maturidade — apenas concentração real de uso) ──
    raw_domains = [
        ("compute", "Computação (EC2)", "EC2 & Compute", [
            ("EC2", m["ec2"]),
            ("EBS", m["ebs"]),
        ]),
        ("serverless", "Serverless & Containers", "Serverless", [
            ("Lambda", m["lambda"]),
            ("ECS", m["ecs"]),
            ("EKS", m["eks"]),
            ("ECR", m["ecr"]),
        ]),
        ("database", "Bancos de Dados", "Bancos", [
            ("RDS", m["rds"]),
            ("DynamoDB", m["dynamodb"]),
            ("ElastiCache", m["elasticache"]),
        ]),
        ("storage", "Armazenamento", "Storage", [
            ("S3", m["s3"]),
            ("EFS", m["efs"]),
            ("Backup", m["backup_plans"]),
        ]),
        ("network", "Redes & Borda", "Redes & CDN", [
            ("VPC", m["vpcs"]),
            ("ALB/NLB", m["albs"]),
            ("NAT GW", m["nat_gws"]),
            ("Route 53", m["route53"]),
            ("CloudFront", m["cloudfront"]),
            ("VPN/TGW", m["vpns"] + m["tgws"]),
            ("EIP", m["eips"]),
        ]),
        ("observability", "Observabilidade & Logs", "Logs & Monitor", [
            ("Log Groups", m["log_groups"]),
            ("CW Alarms", m["cw_alarms"]),
            ("CloudTrail", m["cloudtrail"]),
            ("Flow Logs", m["vpcs_flow_logs"]),
        ]),
        ("security", "Segurança & Identidade", "Segurança", [
            ("IAM Users", m["iam_users"]),
            ("KMS", m["kms"]),
            ("WAF v2", m["waf"]),
            ("ACM", m["acm"]),
            ("GuardDuty", m["guardduty"]),
            ("Security Hub", m["securityhub"]),
        ]),
        ("integration", "APIs & Governança", "APIs & Gov.", [
            ("API Gateway", m["apigw"]),
            ("AWS Config", m["config_enabled"]),
            ("Savings Plans", 1 if m["has_sp"] else 0),
        ]),
    ]

    domain_totals = [sum(cnt for _, cnt in svcs) for _, _, _, svcs in raw_domains]
    grand_total = sum(domain_totals)
    max_dom = max(domain_totals) if domain_totals else 0

    usage_domains = []
    for (did, dname, dshort, svcs), cnt in zip(raw_domains, domain_totals):
        share_pct = round((cnt / grand_total) * 100, 1) if grand_total > 0 else 0.0
        # Curva proporcional ao maior domínio (pende claramente para os serviços mais usados)
        intensity = _clamp(((cnt / max_dom) ** 0.65) * 96) if (max_dom > 0 and cnt > 0) else 0
        active_svcs = [{"name": n, "count": c} for n, c in sorted(svcs, key=lambda x: -x[1]) if c > 0]
        usage_domains.append({
            "id": did,
            "name": dname,
            "shortName": dshort,
            "count": cnt,
            "sharePct": share_pct,
            "intensity": intensity,
            "services": active_svcs,
            "allServices": [{"name": n, "count": c} for n, c in svcs],
        })

    top_dom = max(usage_domains, key=lambda x: x["count"]) if usage_domains else None
    if not top_dom or top_dom["count"] == 0:
        profile_label = "Sem recursos detectados"
    elif top_dom["id"] == "serverless":
        profile_label = "Perfil Serverless / Cloud-Native"
    elif top_dom["id"] in ("compute", "database"):
        profile_label = "Perfil IaaS / Workloads Gerenciados (EC2 & RDS)"
    elif top_dom["id"] == "storage":
        profile_label = "Perfil Data & Storage Heavy"
    elif top_dom["id"] == "network":
        profile_label = "Perfil Conectividade & Borda"
    elif top_dom["id"] == "observability":
        profile_label = "Perfil Alta Telemetria & Logs"
    else:
        profile_label = f"Perfil Predominante: {top_dom['name']}"

    usage_profile = {
        "totalResources": grand_total,
        "dominantDomain": top_dom["name"] if (top_dom and top_dom["count"] > 0) else "—",
        "dominantSharePct": top_dom["sharePct"] if (top_dom and top_dom["count"] > 0) else 0.0,
        "profileLabel": profile_label,
        "domains": usage_domains,
    }

    return {
        "hasData": len(sel_cols) > 0,
        "accountId": cur_id,
        "accountAlias": cur_alias,
        "overallScore": overall,
        "benchmarkAverage": bench_avg,
        "accounts": accounts_index,
        "summary": {
            "accounts": len(sel_cols),
            "regionsActive": len(m["regions"]),
            "totalResources": total_resources,
            "openFindings": len(sel_findings),
            "criticalFindings": critical_f,
            "mtdCostUsd": round(m["mtd_cost"], 2),
            "estimatedMonthlySavingsUsd": round(m["savings_usd"], 2),
        },
        "pillars": pillars,
        "layers": layers,
        "insights": insights,
        "usageProfile": usage_profile,
    }


def build_assets(cols: list[Any], findings: list[dict], account_id: str | None = None) -> dict[str, Any]:
    """Inventário tabular unificado de recursos AWS com status e achados associados."""
    f_by_res: dict[str, list[dict]] = {}
    for f in findings:
        if f.get("status", "aberto") != "aberto":
            continue
        res = str(f.get("resource") or "")
        if res:
            f_by_res.setdefault(res, []).append(f)

    assets: list[dict] = []
    accounts = []

    for col in cols:
        p = col.payload or {}
        if not p:
            continue
        accounts.append({"accountId": col.account_id, "accountAlias": col.alias or col.account_id})
        if account_id and account_id != "all" and col.account_id != account_id:
            continue

        acc_alias = col.alias or col.account_id
        glob = p.get("global") or {}

        for b in glob.get("s3") or []:
            bname = b.get("name") or ""
            flist = f_by_res.get(bname, [])
            st, sk = ("Atenção", "warn") if flist or b.get("policy_public") else ("Ativo", "ok")
            assets.append({
                "id": bname,
                "name": bname,
                "type": "S3",
                "accountId": col.account_id,
                "accountAlias": acc_alias,
                "region": b.get("region") or "global",
                "status": st,
                "statusKind": sk,
                "spec": f"Lifecycle: {'Sim' if b.get('lifecycle') else 'Não'} · Público: {'Sim' if b.get('policy_public') else 'Bloqueado'}",
                "tags": b.get("tags") or {},
                "findings": flist,
            })

        for rname, rdata in (p.get("regions") or {}).items():
            if not isinstance(rdata, dict):
                continue

            for i in rdata.get("ec2") or []:
                iid = i.get("id") or ""
                flist = f_by_res.get(iid, [])
                state = str(i.get("state") or "unknown")
                if state == "running":
                    st, sk = ("Atenção", "warn") if flist else ("Ativo", "ok")
                elif state == "stopped":
                    st, sk = "Parado", "idle"
                else:
                    st, sk = state, "idle"
                assets.append({
                    "id": iid,
                    "name": i.get("name") or iid,
                    "type": "EC2",
                    "accountId": col.account_id,
                    "accountAlias": acc_alias,
                    "region": rname,
                    "status": st,
                    "statusKind": sk,
                    "spec": f"{i.get('type') or '—'} · {i.get('az') or rname}" + (f" · {i.get('public_ip')}" if i.get("public_ip") else ""),
                    "tags": i.get("tags") or {},
                    "findings": flist,
                })

            for d in rdata.get("rds") or []:
                did = d.get("id") or d.get("name") or ""
                flist = f_by_res.get(did, [])
                st, sk = ("Atenção", "bad" if d.get("publicly_accessible") else "warn") if (flist or d.get("publicly_accessible")) else ("Ativo", "ok")
                assets.append({
                    "id": did,
                    "name": did,
                    "type": "RDS",
                    "accountId": col.account_id,
                    "accountAlias": acc_alias,
                    "region": rname,
                    "status": st,
                    "statusKind": sk,
                    "spec": f"{d.get('engine') or 'RDS'} · {d.get('class') or '—'} · {'Multi-AZ' if d.get('multi_az') else 'Single-AZ'}",
                    "tags": d.get("tags") or {},
                    "findings": flist,
                })

            for v in rdata.get("ebs_volumes") or []:
                vid = v.get("id") or ""
                flist = f_by_res.get(vid, [])
                if v.get("state") == "available":
                    st, sk = "Órfão", "bad"
                elif v.get("type") == "gp2":
                    st, sk = "Ocioso/gp2", "warn"
                else:
                    st, sk = "Ativo", "ok"
                assets.append({
                    "id": vid,
                    "name": v.get("name") or vid,
                    "type": "EBS",
                    "accountId": col.account_id,
                    "accountAlias": acc_alias,
                    "region": rname,
                    "status": st,
                    "statusKind": sk,
                    "spec": f"{v.get('type') or 'ebs'} · {v.get('size_gb') or 0} GB · {v.get('state') or '—'}",
                    "tags": v.get("tags") or {},
                    "findings": flist,
                })

            for vpc in rdata.get("vpcs") or []:
                vid = vpc.get("id") or ""
                flist = f_by_res.get(vid, [])
                st, sk = ("Atenção", "warn") if flist else ("Ativo", "ok")
                assets.append({
                    "id": vid,
                    "name": vpc.get("name") or vid,
                    "type": "VPC",
                    "accountId": col.account_id,
                    "accountAlias": acc_alias,
                    "region": rname,
                    "status": st,
                    "statusKind": sk,
                    "spec": f"{vpc.get('cidr') or '—'} · {len(vpc.get('subnets') or [])} subnets · {len(vpc.get('nat_gws') or [])} NAT",
                    "tags": vpc.get("tags") or {},
                    "findings": flist,
                })

            for fn in rdata.get("lambda") or []:
                fname = fn.get("name") or fn.get("arn") or ""
                flist = f_by_res.get(fname, [])
                st, sk = ("Atenção", "warn") if flist else ("Ativo", "ok")
                assets.append({
                    "id": fname,
                    "name": fname,
                    "type": "Lambda",
                    "accountId": col.account_id,
                    "accountAlias": acc_alias,
                    "region": rname,
                    "status": st,
                    "statusKind": sk,
                    "spec": f"{fn.get('runtime') or '—'} · {fn.get('memory_mb') or fn.get('current_mb') or '—'} MB",
                    "tags": fn.get("tags") or {},
                    "findings": flist,
                })

            for alb in rdata.get("albs") or []:
                aname = alb.get("name") or alb.get("arn") or ""
                flist = f_by_res.get(aname, [])
                st, sk = ("Atenção", "warn") if flist else ("Ativo", "ok")
                assets.append({
                    "id": aname,
                    "name": aname,
                    "type": "ALB/NLB",
                    "accountId": col.account_id,
                    "accountAlias": acc_alias,
                    "region": rname,
                    "status": st,
                    "statusKind": sk,
                    "spec": f"{alb.get('type') or 'LB'} · {alb.get('scheme') or '—'}",
                    "tags": alb.get("tags") or {},
                    "findings": flist,
                })

            for eip in rdata.get("eips") or []:
                eid = eip.get("allocation_id") or eip.get("ip") or ""
                if not eip.get("associated"):
                    assets.append({
                        "id": eid,
                        "name": eip.get("ip") or eid,
                        "type": "EIP",
                        "accountId": col.account_id,
                        "accountAlias": acc_alias,
                        "region": rname,
                        "status": "Órfão",
                        "statusKind": "bad",
                        "spec": "IP Elástico não associado (gerando custo ocioso)",
                        "tags": {},
                        "findings": f_by_res.get(eid, []),
                    })

    counts: dict[str, int] = {}
    for a in assets:
        counts[a["type"]] = counts.get(a["type"], 0) + 1

    return {
        "accounts": accounts,
        "total": len(assets),
        "counts": counts,
        "items": assets,
    }
