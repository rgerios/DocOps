"""Diferenças entre duas coletas da mesma conta: o que entrou, saiu e mudou."""
from .findings import Inventory

LABELS = {"vpc": "VPC", "subnet": "Sub-rede", "route": "Rota", "nat": "NAT Gateway", "sg": "Security Group", "ec2": "EC2", "ebs": "Volume EBS",
          "eip": "IP elástico", "asg": "Auto Scaling", "tgw": "Transit Gateway", "vpn": "VPN", "lb": "Load balancer", "tg": "Target group",
          "lambda": "Lambda", "apigw": "API Gateway", "sqs": "Fila SQS", "sns": "Tópico SNS", "ecs": "Cluster ECS", "eks": "Cluster EKS",
          "ecr": "Repositório ECR", "rds": "RDS", "aurora": "Cluster de banco", "ddb": "DynamoDB", "cache": "ElastiCache", "efs": "EFS",
          "s3": "Bucket S3", "cf": "CloudFront", "acm": "Certificado", "kms": "Chave KMS", "secret": "Segredo", "user": "Usuário IAM",
          "trail": "CloudTrail", "waf": "WAF"}

# campos que mudam o tempo todo e não representam mudança de configuração
VOLATILE = {"free_ips", "enis", "attached", "messages", "last_used", "password_last_used", "updated", "size_gb", "objects", "size_mb",
            "image_count", "untagged", "last_push", "running_tasks", "pending_tasks", "running", "pending", "healthy", "unhealthy",
            "items", "stored_mb", "last_accessed", "last_delivery", "last_run", "recovery_points", "in_use", "in_use_by", "tunnels",
            "state_updated", "launch_time", "last_modified", "registered_instances", "active_services", "access_keys", "subscriptions",
            "code_size_bytes", "age_days", "instances", "targets", "_t"}


def _key(t, r):
    if t == "route":
        return f"{r.get('rt_id')}|{r.get('dest')}"
    if t == "vpc":
        return r.get("vpc_id")
    return r.get("id") or r.get("arn") or r.get("name") or r.get("ip") or r.get("domain")


def _label(t, r):
    if t == "route":
        return f"{r.get('dest')} → {r.get('target')} ({r.get('rt_name') or r.get('rt_id')})"
    name = r.get("name") if r.get("name") not in (None, "—") else None
    return name or r.get("domain") or _key(t, r) or "?"


def _clean(r):
    return {k: v for k, v in r.items() if not k.startswith("_") and k not in VOLATILE}


def compare(old_payload: dict | None, new_payload: dict) -> dict:
    if not old_payload:
        return {"baseline": True, "added": 0, "removed": 0, "changed": 0, "items": []}
    a, b = Inventory([old_payload]), Inventory([new_payload])
    items = []
    for t in LABELS:
        old = {_key(t, r): r for r in a.rows(t) if not r.get("_def") and _key(t, r)}
        new = {_key(t, r): r for r in b.rows(t) if not r.get("_def") and _key(t, r)}
        for k in new.keys() - old.keys():
            items.append({"change": "added", "type": t, "type_label": LABELS[t], "id": k, "name": _label(t, new[k]), "region": new[k].get("_r")})
        for k in old.keys() - new.keys():
            items.append({"change": "removed", "type": t, "type_label": LABELS[t], "id": k, "name": _label(t, old[k]), "region": old[k].get("_r")})
        for k in old.keys() & new.keys():
            o, n = _clean(old[k]), _clean(new[k])
            fields = sorted(f for f in set(o) | set(n) if o.get(f) != n.get(f))
            if fields:
                items.append({"change": "changed", "type": t, "type_label": LABELS[t], "id": k, "name": _label(t, new[k]), "region": new[k].get("_r"),
                              "fields": fields[:12],
                              "before": {f: o.get(f) for f in fields[:6] if not isinstance(o.get(f), (list, dict))},
                              "after": {f: n.get(f) for f in fields[:6] if not isinstance(n.get(f), (list, dict))}})
    items.sort(key=lambda x: ({"added": 0, "removed": 1, "changed": 2}[x["change"]], x["type_label"], str(x["name"])))
    return {"baseline": False, "added": sum(1 for i in items if i["change"] == "added"),
            "removed": sum(1 for i in items if i["change"] == "removed"),
            "changed": sum(1 for i in items if i["change"] == "changed"), "items": items[:2000]}
