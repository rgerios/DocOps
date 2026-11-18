import copy
import json

import pyotp
import pytest

from conftest import FIXTURES, H, login


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_csrf_header_required(client, admin):
    login(client, admin["email"], admin["password"])
    r = client.post("/api/tenants", json={"name": "Sem cabeçalho"})
    assert r.status_code == 403


def test_login_lockout_and_generic_errors(client, admin):
    r = login(client, "naoexiste@x.com", "qualquer")
    assert r.status_code == 401 and "inválidos" in r.json()["detail"]


@pytest.fixture(scope="module")
def tenant(client, admin):
    login(client, admin["email"], admin["password"])
    r = client.post("/api/tenants", json={"name": "Cliente Teste", "color": "#336699"}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_member_roles_and_permissions(client, admin, tenant):
    t = tenant["id"]
    login(client, admin["email"], admin["password"])
    r = client.post(f"/api/tenants/{t}/members", json={"email": "leitor@teste.local", "role": "viewer"}, headers=H)
    assert r.status_code == 200, r.text
    temp = r.json()["temp_password"]
    assert temp
    # leitor com senha provisória: só consegue trocar a senha
    login(client, "leitor@teste.local", temp)
    assert client.get("/api/tenants", headers=H).status_code == 403
    r = client.post("/api/auth/password", json={"current": temp, "new": "fraca"}, headers=H)
    assert r.status_code == 400
    assert client.post("/api/auth/password", json={"current": temp, "new": "Leitor#Seguro2026"}, headers=H).status_code == 200
    assert [x["id"] for x in client.get("/api/tenants").json()] == [t]
    # leitor não grava anotações nem cadastra conta
    assert client.put(f"/api/tenants/{t}/notes", json={"changes": {"vpc|1|r|x": {"text": "oi"}}}, headers=H).status_code == 403
    assert client.post(f"/api/tenants/{t}/accounts", json={"account_id": "123456789012", "alias": "x"}, headers=H).status_code == 403
    # outro cliente é invisível
    login(client, admin["email"], admin["password"])
    other = client.post("/api/tenants", json={"name": "Outro Cliente"}, headers=H).json()
    login(client, "leitor@teste.local", "Leitor#Seguro2026")
    assert client.get(f"/api/tenants/{other['id']}/inventory").status_code == 403


def test_mfa_flow(client, admin, tenant):
    login(client, admin["email"], admin["password"])
    r = client.post(f"/api/tenants/{tenant['id']}/members", json={"email": "mfa@teste.local", "role": "analyst"}, headers=H)
    temp = r.json()["temp_password"]
    login(client, "mfa@teste.local", temp)
    client.post("/api/auth/password", json={"current": temp, "new": "Mfa#Usuario2026"}, headers=H)
    setup = client.post("/api/auth/mfa/setup", headers=H).json()
    assert setup["qr"].startswith("data:image/svg+xml")
    assert client.post("/api/auth/mfa/enable", json={"code": "000000"}, headers=H).status_code == 400
    assert client.post("/api/auth/mfa/enable", json={"code": pyotp.TOTP(setup["secret"]).now()}, headers=H).status_code == 200
    r = login(client, "mfa@teste.local", "Mfa#Usuario2026")
    assert r.status_code == 401 and r.json()["detail"]["mfa_required"]
    assert login(client, "mfa@teste.local", "Mfa#Usuario2026", pyotp.TOTP(setup["secret"]).now()).status_code == 200


def test_upload_findings_inventory_and_diff(client, admin, tenant):
    t = tenant["id"]
    login(client, admin["email"], admin["password"])
    files = [("files", ("acme-111111111111.json", open(FIXTURES / "acme-111111111111.json", "rb"), "application/json")),
             ("files", ("mock-123456789012.json", open(FIXTURES / "mock-123456789012.json", "rb"), "application/json"))]
    r = client.post(f"/api/tenants/{t}/collections/upload", files=files, headers=H)
    assert r.status_code == 200, r.text
    assert {x["account_id"] for x in r.json()["created"]} == {"111111111111", "123456789012"}
    inv = client.get(f"/api/tenants/{t}/inventory").json()
    assert len(inv["accounts"]) == 2
    # sub-redes 2 e 3 usam a route table principal (associação implícita) e devem ser privadas
    f = client.get(f"/api/tenants/{t}/findings").json()["findings"]
    titles = {x["title"] for x in f}
    assert "Sobreposição de CIDR entre VPCs" in titles          # 10.40.25.0/24 nas duas contas
    assert "Rotas em blackhole" in titles
    assert "Conta root sem MFA" in titles
    assert "Porta sensível aberta para a internet" in titles
    assert "RDS acessível publicamente" in titles
    assert "Lambda com runtime descontinuado" in titles
    # segunda coleta da conta mock com mudanças -> diff
    p = json.load(open(FIXTURES / "mock-123456789012.json"))
    p2 = copy.deepcopy(p)
    p2["collected_at"] = "2099-01-01T00:00:00+00:00"
    p2["regions"]["us-east-1"]["security_groups"].append({"id": "sg-novo", "name": "novo", "vpc_id": "vpc-x", "inbound": [], "open_world": [], "attached": 0})
    p2["regions"]["us-east-1"]["ec2"][0]["type"] = "m5.large"
    r = client.post(f"/api/tenants/{t}/collections/upload", files=[("files", ("x.json", json.dumps(p2).encode(), "application/json"))], headers=H)
    d = r.json()["created"][0]["diff"]
    assert d["baseline"] is False and d["added"] >= 1 and d["changed"] >= 1
    cid = r.json()["created"][0]["id"]
    full = client.get(f"/api/tenants/{t}/collections/{cid}").json()["diff"]
    assert any(i["change"] == "changed" and "type" in i["fields"] for i in full["items"])


def test_notes_and_finding_status(client, admin, tenant):
    t = tenant["id"]
    login(client, admin["email"], admin["password"])
    fid = client.get(f"/api/tenants/{t}/findings").json()["findings"][0]["id"]
    r = client.put(f"/api/tenants/{t}/notes", json={"changes": {f"finding|{fid}": {"status": "aceito", "text": "risco aceito pela diretoria"},
                                                                "vpc|111111111111|us-east-1|vpc-0aaa000000000001": {"text": "VPC de produção"}}}, headers=H)
    assert r.status_code == 200
    f = {x["id"]: x for x in client.get(f"/api/tenants/{t}/findings").json()["findings"]}
    assert f[fid]["status"] == "aceito"
    inv = client.get(f"/api/tenants/{t}/inventory").json()
    assert inv["notes"]["vpc|111111111111|us-east-1|vpc-0aaa000000000001"]["text"] == "VPC de produção"
    assert client.put(f"/api/tenants/{t}/docs", json={"data": {"env": {"owner": "Rogério"}}}, headers=H).status_code == 200
    assert client.get(f"/api/tenants/{t}/docs").json()["data"]["env"]["owner"] == "Rogério"


def test_teams_alert_on_new_findings(client, admin, tenant, monkeypatch):
    sent = []
    monkeypatch.setattr("app.services.alerts.httpx.post", lambda url, json, timeout: sent.append(json) or type("R", (), {"status_code": 200, "text": ""})())
    t = tenant["id"]
    login(client, admin["email"], admin["password"])
    r = client.put(f"/api/tenants/{t}/settings", json={"teams_webhook": "https://contoso.webhook.office.com/webhookb2/abc", "alert_severities": ["critical", "high", "medium"]}, headers=H)
    assert r.status_code == 200 and r.json()["teams_configured"]
    assert client.put(f"/api/tenants/{t}/settings", json={"teams_webhook": "https://evil.example.com/x"}, headers=H).status_code == 400
    p = json.load(open(FIXTURES / "mock-123456789012.json"))
    p["collected_at"] = "2099-02-01T00:00:00+00:00"
    p["regions"]["us-east-1"]["rds"].append({"id": "db-nova-prod", "engine": "mysql", "publicly_accessible": True, "backup_retention": 7})
    client.post(f"/api/tenants/{t}/collections/upload", files=[("files", ("y.json", json.dumps(p).encode(), "application/json"))], headers=H)
    assert sent, "esperava alerta no Teams"
    assert "achado" in json.dumps(sent[-1], ensure_ascii=False)


def test_assume_role_collection_and_schedule(client, admin, tenant):
    from moto import mock_aws
    t = tenant["id"]
    with mock_aws():
        login(client, admin["email"], admin["password"])
        r = client.post(f"/api/tenants/{t}/accounts", json={"account_id": "222222222222", "alias": "conta-role",
                         "role_arn": "arn:aws:iam::222222222222:role/DocVivaReadOnly", "external_id": "ext-123", "regions": ["us-east-1"]}, headers=H)
        assert r.status_code == 200, r.text
        acc = r.json()
        assert client.post(f"/api/tenants/{t}/accounts/{acc['id']}/test", headers=H).json()["ok"] is True
        r = client.post(f"/api/tenants/{t}/accounts/{acc['id']}/collect", headers=H)
        assert r.status_code == 200, r.text
        cols = client.get(f"/api/tenants/{t}/collections?account_id=222222222222").json()
        assert cols[0]["status"] == "done", cols[0]
        # agendamento: dispara quando vence
        r = client.post(f"/api/tenants/{t}/schedules", json={"name": "Diária", "cron": "0 6 * * *"}, headers=H)
        assert r.status_code == 200, r.text
        assert client.post(f"/api/tenants/{t}/schedules", json={"name": "x", "cron": "*/5 * * * *"}, headers=H).status_code == 400
        from datetime import datetime, timedelta
        from app.scheduler import TZ, tick
        assert tick(datetime.now(TZ) + timedelta(days=1, hours=1)) >= 1


def test_audit_log(client, admin, tenant):
    login(client, admin["email"], admin["password"])
    acts = {a["action"] for a in client.get(f"/api/tenants/{tenant['id']}/audit").json()}
    assert {"collection.uploaded", "notes.saved", "member.added"} <= acts


def test_mfa_lockout_and_secret_validation(client, monkeypatch):
    import pyotp
    from app.config import settings
    from app.db import SessionLocal
    from app.main import bootstrap
    from app.models import User
    from app.security import hash_password

    with SessionLocal() as db:
        u = User(
            email="mfa-lock@teste.local",
            name="MFA Lock",
            password_hash=hash_password("SenhaForte#2026"),
            totp_enabled=True,
            totp_secret=pyotp.random_base32(),
            must_change_password=False,
        )
        db.add(u)
        db.commit()

    for _ in range(settings.max_failed_logins - 1):
        r = login(client, "mfa-lock@teste.local", "SenhaForte#2026", totp="000000")
        assert r.status_code == 401
    r = login(client, "mfa-lock@teste.local", "SenhaForte#2026", totp="000000")
    assert r.status_code == 423

    monkeypatch.setattr(settings, "secret_key", "troque-esta-chave")
    try:
        bootstrap()
        raise AssertionError("Esperava RuntimeError para SECRET_KEY padrão em produção")
    except RuntimeError:
        pass


def test_ai_analysis_config_and_ask(client, admin, tenant, monkeypatch):
    t = tenant["id"]
    login(client, admin["email"], admin["password"])

    r = client.put(
        f"/api/tenants/{t}/ai/config",
        json={"provider": "openrouter", "model": "openai/gpt-4o-mini", "api_key": "sk-or-v1-segredo-123456"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["provider"] == "openrouter"
    assert cfg["api_key_configured"] is True
    assert "segredo" not in (cfg["api_key_hint"] or "")
    assert cfg["stats"]["ec2_total"] >= 2

    captured = {}

    def fake_post(url, headers=None, params=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return type("R", (), {
            "status_code": 200,
            "text": "",
            "json": lambda self: {"choices": [{"message": {"content": "Você possui 2 instâncias EC2 ativas."}}]},
        })()

    monkeypatch.setattr("app.services.ai.httpx.post", fake_post)
    r = client.post(
        f"/api/tenants/{t}/ai/ask",
        json={"question": "Quantas instâncias EC2 tenho no ambiente?"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert "2 instâncias EC2" in r.json()["answer"]
    assert '"ec2_total":' in captured["json"]["messages"][0]["content"]


def test_inventory_time_travel(client, admin, tenant):
    t = tenant["id"]
    login(client, admin["email"], admin["password"])
    inv_latest = client.get(f"/api/tenants/{t}/inventory").json()
    versions = inv_latest["versions"]["123456789012"]
    assert len(versions) >= 2
    oldest_id = versions[-1]["id"]
    latest_id = versions[0]["id"]
    assert oldest_id != latest_id

    inv_old = client.get(f"/api/tenants/{t}/inventory?collection_id={oldest_id}").json()
    selected = {c["account_id"]: c["id"] for c in inv_old["collections"]}
    assert selected["123456789012"] == oldest_id
