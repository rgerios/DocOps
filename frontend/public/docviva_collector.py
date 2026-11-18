#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DocViva Collector v2
=============================================

Inventário completo e somente-leitura de uma conta AWS, em TODAS as regiões
habilitadas, gerando um único arquivo JSON para importar no DocViva.

Uso rápido (CloudShell, conta atual):
    python3 docviva_collector.py --alias producao

Várias contas num arquivo único (a partir de uma conta com permissão de AssumeRole):
    python3 docviva_collector.py \
        --assume-role arn:aws:iam::111111111111:role/DocVivaReadOnly \
                      arn:aws:iam::222222222222:role/DocVivaReadOnly

Consolidar arquivos de contas coletadas separadamente:
    python3 docviva_collector.py merge conta1.json conta2.json -o docviva_bundle.json

Permissões: a política gerenciada `ReadOnlyAccess` cobre tudo. Alternativa mínima:
`ViewOnlyAccess` + `SecurityAudit`. Itens sem permissão são registrados em
"errors" e a coleta continua.

O script NUNCA lê valores de segredos, parâmetros do SSM, variáveis de ambiente
de Lambda, user-data de instâncias nem conteúdo de objetos S3.

Cost Explorer: cada consulta custa US$ 0,01 (são 3 por conta). Use --no-cost
para pular.
"""

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import boto3
    import jmespath
    from botocore.config import Config
    from botocore.exceptions import ClientError, NoCredentialsError
except ImportError:
    sys.exit("boto3 não encontrado. No CloudShell ele já vem instalado; localmente: pip install boto3")

VERSION = "2.0.0"
SCHEMA = "docviva/2"
BUNDLE_SCHEMA = "docviva-bundle/2"

CFG = Config(
    retries={"max_attempts": 10, "mode": "adaptive"},
    connect_timeout=10,
    read_timeout=60,
    max_pool_connections=32,
)

# ─── terminal ────────────────────────────────────────────────────────────────
TTY = sys.stdout.isatty()
def _c(code):
    return (lambda s: "\033[%sm%s\033[0m" % (code, s)) if TTY else (lambda s: s)
BOLD, DIM, CYAN, GREEN, YELLOW, RED = _c("1"), _c("2"), _c("96"), _c("92"), _c("93"), _c("91")
_PRINT_LOCK = threading.Lock()
def say(*a):
    with _PRINT_LOCK:
        print(*a, flush=True)


# ─── helpers ─────────────────────────────────────────────────────────────────
def iso(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, set):
        return sorted(v)
    return str(v)


def tagmap(tags):
    out = {}
    for t in tags or []:
        k = t.get("Key", t.get("key"))
        if k is not None:
            out[k] = t.get("Value", t.get("value", ""))
    return out


def tname(tags, default="—"):
    v = tagmap(tags).get("Name")
    return v if v else default


def P(cli, op, expr, **kw):
    """Paginação genérica: devolve a lista resultante da expressão JMESPath."""
    if cli.can_paginate(op):
        it = cli.get_paginator(op).paginate(**kw).search(expr)
        return [x for x in it if x is not None]
    res = getattr(cli, op)(**kw)
    return jmespath.search(expr, res) or []


_NO = object()  # sentinela: "sem default explícito"


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def short_arn(arn):
    return (arn or "").split("/")[-1].split(":")[-1]


def days_since(d):
    if not d:
        return None
    if isinstance(d, str):
        try:
            d = dt.datetime.fromisoformat(d.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - d).days


# ─── coleta de uma conta ─────────────────────────────────────────────────────
class Account:
    def __init__(self, session, opts, label):
        self.s = session
        self.opts = opts
        self.label = label
        self.errors = []
        self._lock = threading.Lock()
        self._clients = {}

    def c(self, svc, region):
        key = (svc, region)
        with self._lock:
            if key not in self._clients:
                self._clients[key] = self.s.client(svc, region_name=region, config=CFG)
            return self._clients[key]

    def err(self, region, svc, code, msg):
        with self._lock:
            self.errors.append({"region": region, "service": svc, "code": code, "message": (msg or "")[:300]})

    def safe(self, region, svc, fn, default=None, quiet=()):
        try:
            return fn()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "ClientError")
            if code in quiet:
                return default
            self.err(region, svc, code, e.response.get("Error", {}).get("Message", ""))
        except Exception as e:  # noqa: BLE001 — a coleta nunca deve parar
            self.err(region, svc, type(e).__name__, str(e))
        return default


# ═══ REDE ════════════════════════════════════════════════════════════════════
def target_of(route):
    for k in ("GatewayId", "NatGatewayId", "TransitGatewayId", "VpcPeeringConnectionId",
              "NetworkInterfaceId", "InstanceId", "EgressOnlyInternetGatewayId",
              "CarrierGatewayId", "LocalGatewayId", "CoreNetworkArn", "VpcEndpointId"):
        if route.get(k):
            return route[k]
    return "local"


def target_type(t):
    for p, n in (("igw-", "igw"), ("nat-", "nat"), ("tgw-", "tgw"), ("pcx-", "peering"),
                 ("vgw-", "vgw"), ("eni-", "eni"), ("i-", "instance"), ("eigw-", "eigw"),
                 ("vpce-", "endpoint"), ("cagw-", "carrier"), ("lgw-", "local-gw")):
        if t.startswith(p):
            return n
    return "local" if t == "local" else "other"


def sg_rules(perms):
    rules, open_world = [], []
    for p in perms or []:
        proto = p.get("IpProtocol", "-1")
        fp, tp = p.get("FromPort"), p.get("ToPort")
        if proto == "-1":
            port = "all"
        elif fp is None or fp == tp:
            port = "%s:%s" % (proto, fp if fp is not None else "all")
        elif fp == 0 and tp == 65535:
            port = "%s:all" % proto
        else:
            port = "%s:%s-%s" % (proto, fp, tp)
        srcs = [r.get("CidrIp") for r in p.get("IpRanges", [])]
        srcs += [r.get("CidrIpv6") for r in p.get("Ipv6Ranges", [])]
        srcs += [("%s/%s" % (g.get("UserId"), g.get("GroupId")) if g.get("UserId") and g.get("PeeringStatus") else g.get("GroupId"))
                 for g in p.get("UserIdGroupPairs", [])]
        srcs += [pl.get("PrefixListId") for pl in p.get("PrefixListIds", [])]
        srcs = [s for s in srcs if s]
        rules.append({"port": port, "proto": proto, "from": fp, "to": tp, "sources": srcs})
        if any(s in ("0.0.0.0/0", "::/0") for s in srcs):
            open_world.append({"port": port, "proto": proto, "from": fp, "to": tp})
    return rules, open_world


def col_network(A, r):
    ec2 = A.c("ec2", r)
    S = lambda name, fn, d=_NO: A.safe(r, "ec2:" + name, fn, [] if d is _NO else d)

    vpcs = S("vpcs", lambda: P(ec2, "describe_vpcs", "Vpcs[]"))
    subnets = S("subnets", lambda: P(ec2, "describe_subnets", "Subnets[]"))
    rts = S("route_tables", lambda: P(ec2, "describe_route_tables", "RouteTables[]"))
    igws = S("igws", lambda: P(ec2, "describe_internet_gateways", "InternetGateways[]"))
    eigws = S("eigws", lambda: P(ec2, "describe_egress_only_internet_gateways", "EgressOnlyInternetGateways[]"))
    nats = S("nat_gateways", lambda: P(ec2, "describe_nat_gateways", "NatGateways[]",
             Filter=[{"Name": "state", "Values": ["pending", "available", "failed"]}]))
    peers = S("peerings", lambda: P(ec2, "describe_vpc_peering_connections", "VpcPeeringConnections[]",
              Filters=[{"Name": "status-code", "Values": ["active", "pending-acceptance", "provisioning"]}]))
    eps = S("endpoints", lambda: P(ec2, "describe_vpc_endpoints", "VpcEndpoints[]"))
    fls = S("flow_logs", lambda: P(ec2, "describe_flow_logs", "FlowLogs[]"))
    nacls = S("nacls", lambda: P(ec2, "describe_network_acls", "NetworkAcls[]"))
    dhcps = S("dhcp", lambda: P(ec2, "describe_dhcp_options", "DhcpOptions[]"))
    enis = S("enis", lambda: P(ec2, "describe_network_interfaces", "NetworkInterfaces[]"))
    sgs = S("security_groups", lambda: P(ec2, "describe_security_groups", "SecurityGroups[]"))

    # mapas auxiliares
    dhcp_map = {}
    for d in dhcps:
        cfg = {c["Key"]: [v.get("Value") for v in c.get("Values", [])] for c in d.get("DhcpConfigurations", [])}
        dhcp_map[d["DhcpOptionsId"]] = {"domain_name": ",".join(cfg.get("domain-name", [])),
                                        "dns_servers": cfg.get("domain-name-servers", []),
                                        "ntp_servers": cfg.get("ntp-servers", [])}
    eni_by_subnet, eni_by_sg, eni_by_vpc = {}, {}, {}
    for e in enis:
        eni_by_subnet[e.get("SubnetId")] = eni_by_subnet.get(e.get("SubnetId"), 0) + 1
        eni_by_vpc[e.get("VpcId")] = eni_by_vpc.get(e.get("VpcId"), 0) + 1
        for g in e.get("Groups", []):
            eni_by_sg[g["GroupId"]] = eni_by_sg.get(g["GroupId"], 0) + 1

    main_rt, explicit_rt = {}, {}
    for rt in rts:
        for a in rt.get("Associations", []):
            if a.get("Main"):
                main_rt[rt["VpcId"]] = rt["RouteTableId"]
            elif a.get("SubnetId"):
                explicit_rt[a["SubnetId"]] = rt["RouteTableId"]
    rt_by_id = {rt["RouteTableId"]: rt for rt in rts}

    def tier_of(rt):
        if not rt:
            return "isolated", None
        default = [x for x in rt.get("Routes", [])
                   if x.get("DestinationCidrBlock") == "0.0.0.0/0" and x.get("State") != "blackhole"]
        for x in default:
            t = target_of(x)
            if t.startswith("igw-"):
                return "public", t
        if default:
            return "private", target_of(default[0])
        return "isolated", None

    nacl_by_subnet = {}
    for n in nacls:
        for a in n.get("Associations", []):
            nacl_by_subnet[a.get("SubnetId")] = n["NetworkAclId"]

    out_vpcs = []
    for v in vpcs:
        vid = v["VpcId"]
        v_subnets = []
        for sn in (x for x in subnets if x["VpcId"] == vid):
            rt_id = explicit_rt.get(sn["SubnetId"]) or main_rt.get(vid)
            tier, egress = tier_of(rt_by_id.get(rt_id))
            prefix = int(sn["CidrBlock"].split("/")[1])
            v_subnets.append({
                "id": sn["SubnetId"], "name": tname(sn.get("Tags")), "cidr": sn["CidrBlock"],
                "ipv6": [x.get("Ipv6CidrBlock") for x in sn.get("Ipv6CidrBlockAssociationSet", [])],
                "az": sn["AvailabilityZone"], "az_id": sn.get("AvailabilityZoneId"),
                "public": tier == "public", "tier": tier, "egress": egress,
                "free_ips": sn["AvailableIpAddressCount"], "total_ips": max(0, 2 ** (32 - prefix) - 5),
                "map_public_ip": sn.get("MapPublicIpOnLaunch", False), "route_table": rt_id,
                "rt_implicit": sn["SubnetId"] not in explicit_rt, "nacl": nacl_by_subnet.get(sn["SubnetId"]),
                "enis": eni_by_subnet.get(sn["SubnetId"], 0), "state": sn["State"], "tags": tagmap(sn.get("Tags")),
            })
        v_rts = []
        for rt in (x for x in rts if x["VpcId"] == vid):
            routes = []
            for x in rt.get("Routes", []):
                t = target_of(x)
                routes.append({
                    "dest": x.get("DestinationCidrBlock") or x.get("DestinationIpv6CidrBlock") or x.get("DestinationPrefixListId", "—"),
                    "target": t, "target_type": target_type(t), "state": x.get("State", "active"),
                    "origin": x.get("Origin"),
                })
            v_rts.append({
                "id": rt["RouteTableId"], "name": tname(rt.get("Tags")),
                "main": any(a.get("Main") for a in rt.get("Associations", [])),
                "assocs": [a.get("SubnetId") or ("main" if a.get("Main") else a.get("GatewayId", "—"))
                           for a in rt.get("Associations", [])],
                "propagating_vgws": [p.get("GatewayId") for p in rt.get("PropagatingVgws", [])],
                "routes": routes,
            })
        out_vpcs.append({
            "vpc_id": vid, "name": tname(v.get("Tags")), "cidr": v["CidrBlock"],
            "extra_cidrs": [a["CidrBlock"] for a in v.get("CidrBlockAssociationSet", [])
                            if a["CidrBlock"] != v["CidrBlock"] and a.get("CidrBlockState", {}).get("State") == "associated"],
            "ipv6_cidrs": [a.get("Ipv6CidrBlock") for a in v.get("Ipv6CidrBlockAssociationSet", [])],
            "state": v["State"], "is_default": v.get("IsDefault", False),
            "tenancy": v.get("InstanceTenancy", "default"), "dhcp_opts": v.get("DhcpOptionsId", "—"),
            "dhcp": dhcp_map.get(v.get("DhcpOptionsId"), {}), "owner": v.get("OwnerId"),
            "tags": tagmap(v.get("Tags")), "enis": eni_by_vpc.get(vid, 0),
            "subnets": v_subnets, "route_tables": v_rts,
            "igws": [{"id": i["InternetGatewayId"], "name": tname(i.get("Tags")), "state": a.get("State", "attached")}
                     for i in igws for a in i.get("Attachments", []) if a.get("VpcId") == vid],
            "egress_igws": [e["EgressOnlyInternetGatewayId"] for e in eigws
                            if any(a.get("VpcId") == vid for a in e.get("Attachments", []))],
            "nat_gws": [{
                "id": n["NatGatewayId"], "name": tname(n.get("Tags")), "subnet": n.get("SubnetId", "—"),
                "connectivity": n.get("ConnectivityType", "public"), "state": n.get("State"),
                "public_ip": next((a.get("PublicIp") for a in n.get("NatGatewayAddresses", []) if a.get("PublicIp")), "—"),
                "private_ip": next((a.get("PrivateIp") for a in n.get("NatGatewayAddresses", []) if a.get("PrivateIp")), "—"),
                "az": next((s["az"] for s in v_subnets if s["id"] == n.get("SubnetId")), None),
            } for n in nats if n.get("VpcId") == vid],
            "peerings": [{
                "id": p["VpcPeeringConnectionId"], "name": tname(p.get("Tags")), "status": p["Status"]["Code"],
                "requester": "%s (%s) [%s/%s]" % (p["RequesterVpcInfo"].get("VpcId"), p["RequesterVpcInfo"].get("CidrBlock", "—"),
                                                  p["RequesterVpcInfo"].get("OwnerId", "—"), p["RequesterVpcInfo"].get("Region", r)),
                "accepter": "%s (%s) [%s/%s]" % (p["AccepterVpcInfo"].get("VpcId"), p["AccepterVpcInfo"].get("CidrBlock", "—"),
                                                 p["AccepterVpcInfo"].get("OwnerId", "—"), p["AccepterVpcInfo"].get("Region", r)),
                "peer_cidrs": [c.get("CidrBlock") for side in ("RequesterVpcInfo", "AccepterVpcInfo")
                               if p[side].get("VpcId") != vid for c in p[side].get("CidrBlockSet", [])],
            } for p in peers if vid in (p["RequesterVpcInfo"].get("VpcId"), p["AccepterVpcInfo"].get("VpcId"))],
            "endpoints": [{
                "id": e["VpcEndpointId"], "service": e["ServiceName"].split(".")[-1], "service_full": e["ServiceName"],
                "type": e["VpcEndpointType"], "state": e.get("State"), "private_dns": e.get("PrivateDnsEnabled", False),
                "subnets": e.get("SubnetIds", []), "route_tables": e.get("RouteTableIds", []),
            } for e in eps if e.get("VpcId") == vid],
            "flow_logs": [{
                "id": f["FlowLogId"], "destination": f.get("LogDestination") or f.get("LogGroupName", "—"),
                "destination_type": f.get("LogDestinationType"), "traffic_type": f.get("TrafficType"),
                "status": f.get("FlowLogStatus"),
            } for f in fls if f.get("ResourceId") == vid],
            "nacls": [{
                "id": n["NetworkAclId"], "name": tname(n.get("Tags")), "default": n.get("IsDefault", False),
                "subnets": [a.get("SubnetId") for a in n.get("Associations", [])],
                "entries": [{"rule": e.get("RuleNumber"), "egress": e.get("Egress"), "proto": e.get("Protocol"),
                             "action": e.get("RuleAction"), "cidr": e.get("CidrBlock") or e.get("Ipv6CidrBlock"),
                             "ports": ("%s-%s" % (e["PortRange"].get("From"), e["PortRange"].get("To"))) if e.get("PortRange") else "all"}
                            for e in n.get("Entries", [])],
            } for n in nacls if n.get("VpcId") == vid],
        })

    out_sgs = []
    for g in sgs:
        inbound, open_world = sg_rules(g.get("IpPermissions"))
        outbound, _ = sg_rules(g.get("IpPermissionsEgress"))
        out_sgs.append({
            "id": g["GroupId"], "name": g.get("GroupName"), "description": g.get("Description", ""),
            "vpc_id": g.get("VpcId"), "inbound": inbound, "outbound": outbound, "open_world": open_world,
            "attached": eni_by_sg.get(g["GroupId"], 0), "tags": tagmap(g.get("Tags")),
        })

    return {"vpcs": out_vpcs, "security_groups": out_sgs}


def col_connectivity(A, r):
    ec2 = A.c("ec2", r)
    S = lambda name, fn, d=_NO, q=(): A.safe(r, name, fn, [] if d is _NO else d, quiet=q)
    out = {}

    tgws = S("ec2:tgw", lambda: P(ec2, "describe_transit_gateways", "TransitGateways[]"))
    atts = S("ec2:tgw_attachments", lambda: P(ec2, "describe_transit_gateway_attachments", "TransitGatewayAttachments[]"))
    tgw_rts = S("ec2:tgw_route_tables", lambda: P(ec2, "describe_transit_gateway_route_tables", "TransitGatewayRouteTables[]"))
    rt_out = []
    for t in tgw_rts:
        routes = S("ec2:tgw_routes", lambda t=t: ec2.search_transit_gateway_routes(
            TransitGatewayRouteTableId=t["TransitGatewayRouteTableId"],
            Filters=[{"Name": "state", "Values": ["active", "blackhole"]}], MaxResults=1000).get("Routes", []))
        rt_out.append({
            "id": t["TransitGatewayRouteTableId"], "tgw_id": t.get("TransitGatewayId"), "name": tname(t.get("Tags")),
            "routes": [{"dest": x.get("DestinationCidrBlock") or x.get("PrefixListId"), "type": x.get("Type"), "state": x.get("State"),
                        "attachments": [a.get("ResourceId") or a.get("TransitGatewayAttachmentId") for a in x.get("TransitGatewayAttachments", [])]}
                       for x in routes],
        })
    out["transit_gateways"] = [{
        "id": t["TransitGatewayId"], "name": tname(t.get("Tags")), "state": t.get("State"), "owner": t.get("OwnerId"),
        "asn": t.get("Options", {}).get("AmazonSideAsn"),
        "default_rt_assoc": t.get("Options", {}).get("DefaultRouteTableAssociation"),
        "cidrs": t.get("Options", {}).get("TransitGatewayCidrBlocks", []),
        "attachments": [{"id": a["TransitGatewayAttachmentId"], "type": a.get("ResourceType"), "resource": a.get("ResourceId"),
                         "owner": a.get("ResourceOwnerId"), "state": a.get("State"), "name": tname(a.get("Tags"))}
                        for a in atts if a.get("TransitGatewayId") == t["TransitGatewayId"]],
        "route_tables": [x for x in rt_out if x["tgw_id"] == t["TransitGatewayId"]],
    } for t in tgws]

    vgws = S("ec2:vgw", lambda: ec2.describe_vpn_gateways().get("VpnGateways", []))
    out["vpn_gateways"] = [{"id": g["VpnGatewayId"], "name": tname(g.get("Tags")), "state": g.get("State"),
                            "asn": g.get("AmazonSideAsn"),
                            "vpcs": [a.get("VpcId") for a in g.get("VpcAttachments", []) if a.get("State") == "attached"]}
                           for g in vgws if g.get("State") != "deleted"]
    cgws = S("ec2:cgw", lambda: ec2.describe_customer_gateways().get("CustomerGateways", []))
    out["customer_gateways"] = [{"id": g["CustomerGatewayId"], "name": tname(g.get("Tags")), "ip": g.get("IpAddress"),
                                 "asn": g.get("BgpAsn"), "state": g.get("State"), "device": g.get("DeviceName")}
                                for g in cgws if g.get("State") != "deleted"]
    vpns = S("ec2:vpn", lambda: ec2.describe_vpn_connections().get("VpnConnections", []))
    out["vpn_connections"] = [{
        "id": v["VpnConnectionId"], "name": tname(v.get("Tags")), "state": v.get("State"), "type": v.get("Type"),
        "cgw": v.get("CustomerGatewayId"), "vgw": v.get("VpnGatewayId"), "tgw": v.get("TransitGatewayId"),
        "static_routes_only": v.get("Options", {}).get("StaticRoutesOnly"),
        "local_cidr": v.get("Options", {}).get("LocalIpv4NetworkCidr"), "remote_cidr": v.get("Options", {}).get("RemoteIpv4NetworkCidr"),
        "routes": [x.get("DestinationCidrBlock") for x in v.get("Routes", []) if x.get("State") != "deleted"],
        "tunnels": [{"outside_ip": t.get("OutsideIpAddress"), "status": t.get("Status"), "message": t.get("StatusMessage"),
                     "last_change": t.get("LastStatusChange"), "accepted_routes": t.get("AcceptedRouteCount")}
                    for t in v.get("VgwTelemetry", [])],
    } for v in vpns if v.get("State") != "deleted"]

    cvpn = S("ec2:client_vpn", lambda: P(ec2, "describe_client_vpn_endpoints", "ClientVpnEndpoints[]"))
    out["client_vpn"] = [{"id": c["ClientVpnEndpointId"], "name": tname(c.get("Tags")), "status": c.get("Status", {}).get("Code"),
                          "client_cidr": c.get("ClientCidrBlock"), "vpc_id": c.get("VpcId"), "split_tunnel": c.get("SplitTunnel"),
                          "dns": c.get("DnsServers", []),
                          "auth": [a.get("Type") for a in c.get("AuthenticationOptions", [])]} for c in cvpn]

    dx = A.c("directconnect", r)
    conns = S("directconnect:connections", lambda: dx.describe_connections().get("connections", []))
    vifs = S("directconnect:vifs", lambda: dx.describe_virtual_interfaces().get("virtualInterfaces", []))
    out["dx_connections"] = [{"id": c["connectionId"], "name": c.get("connectionName"), "state": c.get("connectionState"),
                              "bandwidth": c.get("bandwidth"), "location": c.get("location"), "partner": c.get("partnerName")}
                             for c in conns]
    out["dx_vifs"] = [{"id": v["virtualInterfaceId"], "name": v.get("virtualInterfaceName"), "type": v.get("virtualInterfaceType"),
                       "state": v.get("virtualInterfaceState"), "vlan": v.get("vlan"), "asn": v.get("asn"),
                       "connection": v.get("connectionId"), "dxgw": v.get("directConnectGatewayId"), "vgw": v.get("virtualGatewayId"),
                       "bgp": [p.get("bgpStatus") for p in v.get("bgpPeers", [])]} for v in vifs]

    rs = A.c("route53resolver", r)
    reps = S("route53resolver:endpoints", lambda: P(rs, "list_resolver_endpoints", "ResolverEndpoints[]"))
    out["resolver_endpoints"] = [{"id": e["Id"], "name": e.get("Name"), "direction": e.get("Direction"),
                                  "ip_count": e.get("IpAddressCount"), "vpc_id": e.get("HostVPCId"), "status": e.get("Status")}
                                 for e in reps]
    rules = S("route53resolver:rules", lambda: P(rs, "list_resolver_rules", "ResolverRules[]"))
    rassoc = S("route53resolver:rule_assocs", lambda: P(rs, "list_resolver_rule_associations", "ResolverRuleAssociations[]"))
    out["resolver_rules"] = [{"id": x["Id"], "name": x.get("Name"), "domain": x.get("DomainName"), "type": x.get("RuleType"),
                              "targets": ["%s:%s" % (t.get("Ip"), t.get("Port")) for t in x.get("TargetIps", [])],
                              "owner": x.get("OwnerId"), "share": x.get("ShareStatus"),
                              "vpcs": [a.get("VPCId") for a in rassoc if a.get("ResolverRuleId") == x["Id"]]}
                             for x in rules if x.get("RuleType") != "RECURSIVE"]
    return out


# ═══ COMPUTE ═════════════════════════════════════════════════════════════════
_STOP_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})")


def col_compute(A, r):
    ec2 = A.c("ec2", r)
    S = lambda name, fn, d=_NO: A.safe(r, name, fn, [] if d is _NO else d)
    out = {}

    ssm_info = S("ssm:instance_information", lambda: P(A.c("ssm", r), "describe_instance_information", "InstanceInformationList[]"))
    ssm_map = {i["InstanceId"]: i for i in ssm_info}
    out["ssm_managed"] = [{"id": i["InstanceId"], "ping": i.get("PingStatus"), "platform": i.get("PlatformName"),
                           "platform_version": i.get("PlatformVersion"), "agent": i.get("AgentVersion"),
                           "type": i.get("ResourceType"), "computer_name": i.get("ComputerName"), "ip": i.get("IPAddress")}
                          for i in ssm_info]

    inst = S("ec2:instances", lambda: P(ec2, "describe_instances", "Reservations[].Instances[]"))
    rows = []
    for i in inst:
        st = i.get("State", {}).get("Name")
        if st == "terminated":
            continue
        reason = i.get("StateTransitionReason", "") or ""
        m = _STOP_RE.search(reason)
        ssm = ssm_map.get(i["InstanceId"])
        rows.append({
            "id": i["InstanceId"], "name": tname(i.get("Tags")), "type": i.get("InstanceType"), "state": st,
            "platform": i.get("PlatformDetails") or i.get("Platform") or "Linux/UNIX", "arch": i.get("Architecture"),
            "az": i.get("Placement", {}).get("AvailabilityZone"), "vpc_id": i.get("VpcId"), "subnet_id": i.get("SubnetId"),
            "private_ip": i.get("PrivateIpAddress"), "public_ip": i.get("PublicIpAddress"), "ami": i.get("ImageId"),
            "key_name": i.get("KeyName"), "iam_profile": short_arn(i.get("IamInstanceProfile", {}).get("Arn")) or None,
            "security_groups": [g["GroupId"] for g in i.get("SecurityGroups", [])],
            "launch_time": i.get("LaunchTime"), "stopped_since": m.group(1) if (st == "stopped" and m) else None,
            "imds_v2": i.get("MetadataOptions", {}).get("HttpTokens") == "required",
            "monitoring": i.get("Monitoring", {}).get("State"), "lifecycle": i.get("InstanceLifecycle", "on-demand"),
            "root_device": i.get("RootDeviceType"), "ebs_optimized": i.get("EbsOptimized"),
            "volumes": [b["Ebs"]["VolumeId"] for b in i.get("BlockDeviceMappings", []) if b.get("Ebs")],
            "ssm": (ssm or {}).get("PingStatus", "not-managed"), "os": (ssm or {}).get("PlatformName"),
            "tags": tagmap(i.get("Tags")),
        })
    out["ec2"] = rows

    vols = S("ec2:volumes", lambda: P(ec2, "describe_volumes", "Volumes[]"))
    out["ebs_volumes"] = [{
        "id": v["VolumeId"], "name": tname(v.get("Tags")), "size_gb": v.get("Size"), "type": v.get("VolumeType"),
        "iops": v.get("Iops"), "throughput": v.get("Throughput"), "encrypted": v.get("Encrypted"), "state": v.get("State"),
        "az": v.get("AvailabilityZone"), "created": v.get("CreateTime"),
        "attached_to": [a.get("InstanceId") for a in v.get("Attachments", [])], "tags": tagmap(v.get("Tags")),
    } for v in vols]

    snaps = S("ec2:snapshots", lambda: P(ec2, "describe_snapshots", "Snapshots[]", OwnerIds=["self"]))
    out["ebs_snapshots_summary"] = {
        "count": len(snaps), "total_gb": sum(s.get("VolumeSize", 0) for s in snaps),
        "oldest": min((s["StartTime"] for s in snaps), default=None),
        "unencrypted": sum(1 for s in snaps if not s.get("Encrypted")),
        "older_than_365d": sum(1 for s in snaps if (days_since(s.get("StartTime")) or 0) > 365),
    }
    amis = S("ec2:images", lambda: ec2.describe_images(Owners=["self"]).get("Images", []))
    out["amis"] = [{"id": a["ImageId"], "name": a.get("Name"), "created": a.get("CreationDate"), "state": a.get("State"),
                    "public": a.get("Public", False), "platform": a.get("PlatformDetails")} for a in amis]

    eips = S("ec2:eips", lambda: ec2.describe_addresses().get("Addresses", []))
    out["eips"] = [{"ip": e.get("PublicIp"), "allocation_id": e.get("AllocationId"), "name": tname(e.get("Tags")),
                    "instance": e.get("InstanceId"), "eni": e.get("NetworkInterfaceId"), "private_ip": e.get("PrivateIpAddress"),
                    "associated": bool(e.get("AssociationId"))} for e in eips]

    asg = A.c("autoscaling", r)
    groups = S("autoscaling:groups", lambda: P(asg, "describe_auto_scaling_groups", "AutoScalingGroups[]"))
    out["asg"] = [{
        "name": g["AutoScalingGroupName"], "min": g.get("MinSize"), "max": g.get("MaxSize"), "desired": g.get("DesiredCapacity"),
        "instances": len(g.get("Instances", [])),
        "healthy": sum(1 for x in g.get("Instances", []) if x.get("HealthStatus") == "Healthy"),
        "launch": (g.get("LaunchTemplate") or {}).get("LaunchTemplateName") or g.get("LaunchConfigurationName")
                  or ((g.get("MixedInstancesPolicy") or {}).get("LaunchTemplate", {}).get("LaunchTemplateSpecification", {}).get("LaunchTemplateName")),
        "health_check": g.get("HealthCheckType"), "subnets": (g.get("VPCZoneIdentifier") or "").split(",") if g.get("VPCZoneIdentifier") else [],
        "target_groups": [short_arn(t) for t in g.get("TargetGroupARNs", [])], "created": g.get("CreatedTime"),
    } for g in groups]

    eb = A.c("elasticbeanstalk", r)
    envs = S("elasticbeanstalk:environments", lambda: eb.describe_environments(IncludeDeleted=False).get("Environments", []))
    out["beanstalk"] = [{"name": e.get("EnvironmentName"), "app": e.get("ApplicationName"), "status": e.get("Status"),
                         "health": e.get("Health"), "platform": e.get("PlatformArn", "").split("/")[-1] or e.get("SolutionStackName"),
                         "cname": e.get("CNAME"), "updated": e.get("DateUpdated")} for e in envs]
    return out


def col_loadbalancers(A, r):
    S = lambda name, fn, d=_NO, q=(): A.safe(r, name, fn, [] if d is _NO else d, quiet=q)
    e2 = A.c("elbv2", r)
    lbs = S("elbv2:lbs", lambda: P(e2, "describe_load_balancers", "LoadBalancers[]"))
    tgs = S("elbv2:target_groups", lambda: P(e2, "describe_target_groups", "TargetGroups[]"))
    tg_rows = []
    for t in tgs:
        th = S("elbv2:target_health", lambda t=t: e2.describe_target_health(TargetGroupArn=t["TargetGroupArn"]).get("TargetHealthDescriptions", []))
        states = [x.get("TargetHealth", {}).get("State") for x in th]
        tg_rows.append({"arn": t["TargetGroupArn"], "name": t.get("TargetGroupName"), "protocol": t.get("Protocol"),
                        "port": t.get("Port"), "target_type": t.get("TargetType"), "vpc_id": t.get("VpcId"),
                        "lbs": [a.split("/")[-2] for a in t.get("LoadBalancerArns", [])],
                        "health_path": t.get("HealthCheckPath"), "targets": len(states),
                        "healthy": states.count("healthy"), "unhealthy": states.count("unhealthy")})
    rows = []
    for lb in lbs:
        arn = lb["LoadBalancerArn"]
        ls = S("elbv2:listeners", lambda: P(e2, "describe_listeners", "Listeners[]", LoadBalancerArn=arn))
        attrs = S("elbv2:attributes", lambda: e2.describe_load_balancer_attributes(LoadBalancerArn=arn).get("Attributes", []))
        am = {a["Key"]: a["Value"] for a in attrs}
        rows.append({
            "name": lb["LoadBalancerName"], "arn": arn, "type": lb.get("Type"), "scheme": lb.get("Scheme"),
            "state": lb.get("State", {}).get("Code"), "dns": lb.get("DNSName"), "vpc_id": lb.get("VpcId"),
            "azs": [z.get("ZoneName") for z in lb.get("AvailabilityZones", [])],
            "subnets": [z.get("SubnetId") for z in lb.get("AvailabilityZones", [])],
            "security_groups": lb.get("SecurityGroups", []), "created": lb.get("CreatedTime"),
            "listeners": [{"port": l.get("Port"), "protocol": l.get("Protocol"), "ssl_policy": l.get("SslPolicy"),
                           "certs": len(l.get("Certificates", [])),
                           "action": (l.get("DefaultActions") or [{}])[0].get("Type")} for l in ls],
            "target_groups": [t["name"] for t in tg_rows if lb["LoadBalancerName"] in t["lbs"]],
            "deletion_protection": am.get("deletion_protection.enabled") == "true",
            "access_logs": am.get("access_logs.s3.enabled") == "true",
            "drop_invalid_headers": am.get("routing.http.drop_invalid_header_fields.enabled") == "true",
        })
    e1 = A.c("elb", r)
    clbs = S("elb:classic", lambda: P(e1, "describe_load_balancers", "LoadBalancerDescriptions[]"))
    for lb in clbs:
        rows.append({
            "name": lb["LoadBalancerName"], "arn": None, "type": "classic", "scheme": lb.get("Scheme"), "state": "active",
            "dns": lb.get("DNSName"), "vpc_id": lb.get("VPCId"), "azs": lb.get("AvailabilityZones", []),
            "subnets": lb.get("Subnets", []), "security_groups": lb.get("SecurityGroups", []), "created": lb.get("CreatedTime"),
            "listeners": [{"port": l["Listener"].get("LoadBalancerPort"), "protocol": l["Listener"].get("Protocol"),
                           "certs": 1 if l["Listener"].get("SSLCertificateId") else 0, "action": "forward"}
                          for l in lb.get("ListenerDescriptions", [])],
            "instances": len(lb.get("Instances", [])), "target_groups": [], "deletion_protection": None, "access_logs": None,
        })
    return {"load_balancers": rows, "target_groups": tg_rows}


# ═══ SERVERLESS / INTEGRAÇÃO ═════════════════════════════════════════════════
def col_serverless(A, r):
    S = lambda name, fn, d=_NO, q=(): A.safe(r, name, fn, [] if d is _NO else d, quiet=q)
    out = {}
    lm = A.c("lambda", r)
    fns = S("lambda:functions", lambda: P(lm, "list_functions", "Functions[]"))
    out["lambda"] = [{
        "name": f["FunctionName"], "runtime": f.get("Runtime") or f.get("PackageType"), "arch": (f.get("Architectures") or ["x86_64"])[0],
        "handler": f.get("Handler"), "memory_mb": f.get("MemorySize"), "timeout_s": f.get("Timeout"),
        "ephemeral_mb": (f.get("EphemeralStorage") or {}).get("Size"), "state": f.get("State", "Active"),
        "last_modified": f.get("LastModified"), "code_size_bytes": f.get("CodeSize"), "role": short_arn(f.get("Role")),
        "vpc_id": (f.get("VpcConfig") or {}).get("VpcId") or None, "subnets": (f.get("VpcConfig") or {}).get("SubnetIds", []),
        "security_groups": (f.get("VpcConfig") or {}).get("SecurityGroupIds", []), "layers": len(f.get("Layers", [])),
        "env_vars": len(((f.get("Environment") or {}).get("Variables") or {})),  # só a quantidade, nunca os valores
        "description": f.get("Description", ""), "package": f.get("PackageType"),
        "tracing": (f.get("TracingConfig") or {}).get("Mode"),
    } for f in fns]

    ag = A.c("apigateway", r)
    rest = S("apigateway:rest", lambda: P(ag, "get_rest_apis", "items[]"))
    rows = []
    for a in rest:
        stages = S("apigateway:stages", lambda a=a: ag.get_stages(restApiId=a["id"]).get("item", []))
        rows.append({"id": a["id"], "name": a.get("name"), "kind": "REST",
                     "endpoint": ",".join((a.get("endpointConfiguration") or {}).get("types", [])),
                     "stages": [s.get("stageName") for s in stages], "created": a.get("createdDate"),
                     "waf": any(s.get("webAclArn") for s in stages)})
    ag2 = A.c("apigatewayv2", r)
    v2 = S("apigatewayv2:apis", lambda: P(ag2, "get_apis", "Items[]"))
    for a in v2:
        rows.append({"id": a["ApiId"], "name": a.get("Name"), "kind": a.get("ProtocolType"), "endpoint": a.get("ApiEndpoint"),
                     "stages": [], "created": a.get("CreatedDate"), "waf": None})
    out["api_gateway"] = rows

    sqs = A.c("sqs", r)
    urls = S("sqs:queues", lambda: P(sqs, "list_queues", "QueueUrls[]"))
    qrows = []
    for u in urls[:1000]:
        at = S("sqs:attributes", lambda u=u: sqs.get_queue_attributes(QueueUrl=u, AttributeNames=[
            "ApproximateNumberOfMessages", "KmsMasterKeyId", "SqsManagedSseEnabled", "RedrivePolicy", "FifoQueue",
            "MessageRetentionPeriod"]).get("Attributes", {}), d={})
        qrows.append({"name": u.split("/")[-1], "url": u, "messages": int(at.get("ApproximateNumberOfMessages", 0) or 0),
                      "encrypted": bool(at.get("KmsMasterKeyId")) or at.get("SqsManagedSseEnabled") == "true",
                      "dlq": bool(at.get("RedrivePolicy")), "fifo": at.get("FifoQueue") == "true",
                      "retention_days": int(at.get("MessageRetentionPeriod", 0) or 0) // 86400})
    out["sqs"] = qrows

    sns = A.c("sns", r)
    topics = S("sns:topics", lambda: P(sns, "list_topics", "Topics[].TopicArn"))
    trows = []
    for t in topics[:1000]:
        at = S("sns:attributes", lambda t=t: sns.get_topic_attributes(TopicArn=t).get("Attributes", {}), d={})
        trows.append({"name": t.split(":")[-1], "arn": t, "subscriptions": int(at.get("SubscriptionsConfirmed", 0) or 0),
                      "encrypted": bool(at.get("KmsMasterKeyId"))})
    out["sns"] = trows

    evb = A.c("events", r)
    buses = S("events:buses", lambda: P(evb, "list_event_buses", "EventBuses[]"))
    erules = S("events:rules", lambda: P(evb, "list_rules", "Rules[]"))
    out["eventbridge"] = {"buses": [b.get("Name") for b in buses],
                          "rules": [{"name": x.get("Name"), "state": x.get("State"), "schedule": x.get("ScheduleExpression"),
                                     "bus": x.get("EventBusName")} for x in erules]}
    sfn = A.c("stepfunctions", r)
    sms = S("stepfunctions:machines", lambda: P(sfn, "list_state_machines", "stateMachines[]"))
    out["step_functions"] = [{"name": m.get("name"), "type": m.get("type"), "created": m.get("creationDate")} for m in sms]
    kin = A.c("kinesis", r)
    streams = S("kinesis:streams", lambda: P(kin, "list_streams", "StreamNames[]"))
    out["kinesis"] = [{"name": s} for s in streams]
    return out


# ═══ CONTAINERS ══════════════════════════════════════════════════════════════
def col_containers(A, r):
    S = lambda name, fn, d=_NO, q=(): A.safe(r, name, fn, [] if d is _NO else d, quiet=q)
    out = {}
    ecs = A.c("ecs", r)
    carns = S("ecs:clusters", lambda: P(ecs, "list_clusters", "clusterArns[]"))
    clusters = []
    for batch in chunks(carns, 100):
        clusters += S("ecs:describe_clusters", lambda b=batch: ecs.describe_clusters(clusters=b, include=["SETTINGS"]).get("clusters", []))
    rows = []
    for c in clusters:
        sarns = S("ecs:services", lambda c=c: P(ecs, "list_services", "serviceArns[]", cluster=c["clusterArn"]))
        services = []
        for batch in chunks(sarns, 10):  # limite da API: 10 por chamada
            services += S("ecs:describe_services", lambda b=batch, c=c: ecs.describe_services(cluster=c["clusterArn"], services=b).get("services", []))
        rows.append({
            "name": c["clusterName"], "arn": c["clusterArn"], "status": c.get("status"),
            "active_services": c.get("activeServicesCount", 0), "running_tasks": c.get("runningTasksCount", 0),
            "pending_tasks": c.get("pendingTasksCount", 0), "registered_instances": c.get("registeredContainerInstancesCount", 0),
            "container_insights": any(s.get("name") == "containerInsights" and s.get("value") in ("enabled", "enhanced") for s in c.get("settings", [])),
            "capacity_providers": c.get("capacityProviders", []),
            "services": [{
                "name": s["serviceName"], "status": s.get("status"), "desired": s.get("desiredCount"), "running": s.get("runningCount"),
                "pending": s.get("pendingCount"),
                "launch_type": s.get("launchType") or ",".join(cp.get("capacityProvider") for cp in s.get("capacityProviderStrategy", [])),
                "task_definition": (s.get("taskDefinition") or "").split("/")[-1],
                "load_balancers": [lb.get("targetGroupArn", "").split("/")[-2] if lb.get("targetGroupArn") else lb.get("loadBalancerName")
                                   for lb in s.get("loadBalancers", [])],
                "subnets": (s.get("networkConfiguration") or {}).get("awsvpcConfiguration", {}).get("subnets", []),
                "public_ip": (s.get("networkConfiguration") or {}).get("awsvpcConfiguration", {}).get("assignPublicIp"),
                "security_groups": (s.get("networkConfiguration") or {}).get("awsvpcConfiguration", {}).get("securityGroups", []),
                "exec_enabled": s.get("enableExecuteCommand", False),
            } for s in services],
        })
    out["ecs"] = rows

    eks = A.c("eks", r)
    names = S("eks:clusters", lambda: P(eks, "list_clusters", "clusters[]"))
    erows = []
    for n in names:
        c = S("eks:describe", lambda n=n: eks.describe_cluster(name=n)["cluster"], d={})
        if not c:
            continue
        ngs = []
        for ng in S("eks:nodegroups", lambda n=n: P(eks, "list_nodegroups", "nodegroups[]", clusterName=n)):
            d = S("eks:nodegroup", lambda n=n, ng=ng: eks.describe_nodegroup(clusterName=n, nodegroupName=ng)["nodegroup"], d={})
            if d:
                sc = d.get("scalingConfig", {})
                ngs.append({"name": ng, "status": d.get("status"), "version": d.get("version"), "instance_types": d.get("instanceTypes", []),
                            "capacity": d.get("capacityType"), "ami_type": d.get("amiType"),
                            "desired": sc.get("desiredSize"), "min": sc.get("minSize"), "max": sc.get("maxSize")})
        addons = S("eks:addons", lambda n=n: P(eks, "list_addons", "addons[]", clusterName=n))
        fps = S("eks:fargate", lambda n=n: P(eks, "list_fargate_profiles", "fargateProfileNames[]", clusterName=n))
        vc = c.get("resourcesVpcConfig", {})
        logging_on = [t for lc in c.get("logging", {}).get("clusterLogging", []) if lc.get("enabled") for t in lc.get("types", [])]
        erows.append({
            "name": n, "status": c.get("status"), "version": c.get("version"), "platform_version": c.get("platformVersion"),
            "vpc_id": vc.get("vpcId"), "subnets": vc.get("subnetIds", []), "private_access": vc.get("endpointPrivateAccess"),
            "public_access": vc.get("endpointPublicAccess"), "public_cidrs": vc.get("publicAccessCidrs", []),
            "logging": logging_on, "secrets_encryption": bool(c.get("encryptionConfig")),
            "auth_mode": (c.get("accessConfig") or {}).get("authenticationMode"),
            "support_type": (c.get("upgradePolicy") or {}).get("supportType"),
            "created": c.get("createdAt"), "nodegroups": ngs, "addons": addons, "fargate_profiles": fps,
        })
    out["eks"] = erows

    ecr = A.c("ecr", r)
    repos = S("ecr:repos", lambda: P(ecr, "describe_repositories", "repositories[]"))
    rrows = []
    for rp in repos:
        imgs = S("ecr:images", lambda rp=rp: P(ecr, "describe_images", "imageDetails[]", repositoryName=rp["repositoryName"]))
        lc = S("ecr:lifecycle", lambda rp=rp: bool(ecr.get_lifecycle_policy(repositoryName=rp["repositoryName"])), d=False,
               q=("LifecyclePolicyNotFoundException",))
        pushes = [i.get("imagePushedAt") for i in imgs if i.get("imagePushedAt")]
        rrows.append({
            "name": rp["repositoryName"], "uri": rp.get("repositoryUri"), "created": rp.get("createdAt"),
            "scan_on_push": (rp.get("imageScanningConfiguration") or {}).get("scanOnPush", False),
            "immutable": rp.get("imageTagMutability") == "IMMUTABLE",
            "encryption": (rp.get("encryptionConfiguration") or {}).get("encryptionType", "AES256"),
            "image_count": len(imgs), "size_mb": round(sum(i.get("imageSizeInBytes", 0) for i in imgs) / 1048576, 1),
            "untagged": sum(1 for i in imgs if not i.get("imageTags")), "last_push": max(pushes) if pushes else None,
            "lifecycle_policy": lc,
        })
    out["ecr"] = rrows
    return out


# ═══ DADOS ═══════════════════════════════════════════════════════════════════
def col_data(A, r):
    S = lambda name, fn, d=_NO, q=(): A.safe(r, name, fn, [] if d is _NO else d, quiet=q)
    out = {}
    rds = A.c("rds", r)
    dbs = S("rds:instances", lambda: P(rds, "describe_db_instances", "DBInstances[]"))
    out["rds"] = [{
        "id": d["DBInstanceIdentifier"], "engine": d.get("Engine"), "engine_version": d.get("EngineVersion"),
        "class": d.get("DBInstanceClass"), "status": d.get("DBInstanceStatus"), "cluster": d.get("DBClusterIdentifier"),
        "multi_az": d.get("MultiAZ"), "az": d.get("AvailabilityZone"), "storage_gb": d.get("AllocatedStorage"),
        "storage_type": d.get("StorageType"), "iops": d.get("Iops"), "encrypted": d.get("StorageEncrypted"),
        "endpoint": (d.get("Endpoint") or {}).get("Address"), "port": (d.get("Endpoint") or {}).get("Port"),
        "vpc_id": (d.get("DBSubnetGroup") or {}).get("VpcId"), "subnet_group": (d.get("DBSubnetGroup") or {}).get("DBSubnetGroupName"),
        "security_groups": [g.get("VpcSecurityGroupId") for g in d.get("VpcSecurityGroups", [])],
        "publicly_accessible": d.get("PubliclyAccessible"), "backup_retention": d.get("BackupRetentionPeriod"),
        "deletion_protection": d.get("DeletionProtection"), "performance_insights": d.get("PerformanceInsightsEnabled"),
        "auto_minor_upgrade": d.get("AutoMinorVersionUpgrade"), "iam_auth": d.get("IAMDatabaseAuthenticationEnabled"),
        "ca_cert": d.get("CACertificateIdentifier"), "maintenance": d.get("PreferredMaintenanceWindow"),
        "created": d.get("InstanceCreateTime"), "tags": tagmap(d.get("TagList")),
    } for d in dbs]
    cls = S("rds:clusters", lambda: P(rds, "describe_db_clusters", "DBClusters[]"))
    out["rds_clusters"] = [{
        "id": c["DBClusterIdentifier"], "engine": c.get("Engine"), "engine_version": c.get("EngineVersion"),
        "mode": c.get("EngineMode"), "status": c.get("Status"), "multi_az": c.get("MultiAZ"),
        "members": [{"id": m.get("DBInstanceIdentifier"), "writer": m.get("IsClusterWriter")} for m in c.get("DBClusterMembers", [])],
        "encrypted": c.get("StorageEncrypted"), "endpoint": c.get("Endpoint"), "reader_endpoint": c.get("ReaderEndpoint"),
        "port": c.get("Port"), "backup_retention": c.get("BackupRetentionPeriod"), "deletion_protection": c.get("DeletionProtection"),
        "serverless_v2": c.get("ServerlessV2ScalingConfiguration"), "global_cluster": bool(c.get("GlobalWriteForwardingStatus")),
        "security_groups": [g.get("VpcSecurityGroupId") for g in c.get("VpcSecurityGroups", [])],
        "subnet_group": c.get("DBSubnetGroup"), "created": c.get("ClusterCreateTime"),
    } for c in cls]
    msnaps = S("rds:snapshots", lambda: P(rds, "describe_db_snapshots", "DBSnapshots[]", SnapshotType="manual"))
    out["rds_manual_snapshots"] = {"count": len(msnaps), "total_gb": sum(s.get("AllocatedStorage", 0) for s in msnaps)}

    ddb = A.c("dynamodb", r)
    tnames = S("dynamodb:tables", lambda: P(ddb, "list_tables", "TableNames[]"))
    trows = []
    for t in tnames[:500]:
        d = S("dynamodb:describe", lambda t=t: ddb.describe_table(TableName=t)["Table"], d={})
        pitr = S("dynamodb:pitr", lambda t=t: ddb.describe_continuous_backups(TableName=t)["ContinuousBackupsDescription"]
                 .get("PointInTimeRecoveryDescription", {}).get("PointInTimeRecoveryStatus"), d=None)
        trows.append({"name": t, "status": d.get("TableStatus"), "items": d.get("ItemCount"),
                      "size_mb": round((d.get("TableSizeBytes") or 0) / 1048576, 2),
                      "billing": (d.get("BillingModeSummary") or {}).get("BillingMode", "PROVISIONED"),
                      "pitr": pitr == "ENABLED", "gsi": len(d.get("GlobalSecondaryIndexes", [])),
                      "stream": bool((d.get("StreamSpecification") or {}).get("StreamEnabled")),
                      "replicas": [x.get("RegionName") for x in d.get("Replicas", [])],
                      "deletion_protection": d.get("DeletionProtectionEnabled"),
                      "encryption": (d.get("SSEDescription") or {}).get("SSEType", "AWS_OWNED")})
    out["dynamodb"] = trows

    ec = A.c("elasticache", r)
    rgs = S("elasticache:replication_groups", lambda: P(ec, "describe_replication_groups", "ReplicationGroups[]"))
    ccs = S("elasticache:clusters", lambda: P(ec, "describe_cache_clusters", "CacheClusters[]", ShowCacheNodeInfo=False))
    rows = [{"id": g["ReplicationGroupId"], "kind": "replication-group", "engine": g.get("Engine", "redis"),
             "status": g.get("Status"), "node_type": g.get("CacheNodeType"), "nodes": len(g.get("MemberClusters", [])),
             "cluster_mode": g.get("ClusterEnabled"), "failover": g.get("AutomaticFailover"), "multi_az": g.get("MultiAZ"),
             "encrypted_rest": g.get("AtRestEncryptionEnabled"), "encrypted_transit": g.get("TransitEncryptionEnabled"),
             "auth": g.get("AuthTokenEnabled")} for g in rgs]
    in_rg = {m for g in rgs for m in g.get("MemberClusters", [])}
    rows += [{"id": c["CacheClusterId"], "kind": "cluster", "engine": c.get("Engine"), "engine_version": c.get("EngineVersion"),
              "status": c.get("CacheClusterStatus"), "node_type": c.get("CacheNodeType"), "nodes": c.get("NumCacheNodes"),
              "encrypted_rest": c.get("AtRestEncryptionEnabled"), "encrypted_transit": c.get("TransitEncryptionEnabled")}
             for c in ccs if c["CacheClusterId"] not in in_rg]
    out["elasticache"] = rows

    osr = A.c("opensearch", r)
    dn = S("opensearch:domains", lambda: [d["DomainName"] for d in osr.list_domain_names().get("DomainNames", [])])
    orows = []
    for b in chunks(dn, 5):
        for d in S("opensearch:describe", lambda b=b: osr.describe_domains(DomainNames=b).get("DomainStatusList", [])):
            cc = d.get("ClusterConfig", {})
            orows.append({"name": d["DomainName"], "version": d.get("EngineVersion"), "instance_type": cc.get("InstanceType"),
                          "instances": cc.get("InstanceCount"), "vpc": bool(d.get("VPCOptions")),
                          "encrypted": (d.get("EncryptionAtRestOptions") or {}).get("Enabled"),
                          "node_to_node": (d.get("NodeToNodeEncryptionOptions") or {}).get("Enabled"),
                          "endpoint": d.get("Endpoint") or (d.get("Endpoints") or {}).get("vpc")})
    out["opensearch"] = orows

    efs = A.c("efs", r)
    fss = S("efs:filesystems", lambda: P(efs, "describe_file_systems", "FileSystems[]"))
    out["efs"] = [{"id": f["FileSystemId"], "name": f.get("Name") or tname(f.get("Tags")),
                   "size_gb": round((f.get("SizeInBytes") or {}).get("Value", 0) / 1073741824, 2),
                   "encrypted": f.get("Encrypted"), "performance": f.get("PerformanceMode"), "throughput": f.get("ThroughputMode"),
                   "mount_targets": f.get("NumberOfMountTargets"), "state": f.get("LifeCycleState")} for f in fss]
    fsx = A.c("fsx", r)
    fxs = S("fsx:filesystems", lambda: P(fsx, "describe_file_systems", "FileSystems[]"))
    out["fsx"] = [{"id": f["FileSystemId"], "type": f.get("FileSystemType"), "storage_gb": f.get("StorageCapacity"),
                   "state": f.get("Lifecycle"), "vpc_id": f.get("VpcId"), "dns": f.get("DNSName"), "name": tname(f.get("Tags"))} for f in fxs]
    rs = A.c("redshift", r)
    rcs = S("redshift:clusters", lambda: P(rs, "describe_clusters", "Clusters[]"))
    out["redshift"] = [{"id": c["ClusterIdentifier"], "node_type": c.get("NodeType"), "nodes": c.get("NumberOfNodes"),
                        "status": c.get("ClusterStatus"), "encrypted": c.get("Encrypted"), "public": c.get("PubliclyAccessible"),
                        "vpc_id": c.get("VpcId")} for c in rcs]
    mq = A.c("mq", r)
    brokers = S("mq:brokers", lambda: P(mq, "list_brokers", "BrokerSummaries[]"))
    out["mq"] = [{"id": b.get("BrokerId"), "name": b.get("BrokerName"), "engine": b.get("EngineType"), "state": b.get("BrokerState"),
                  "deployment": b.get("DeploymentMode"), "instance": b.get("HostInstanceType")} for b in brokers]
    kf = A.c("kafka", r)
    msk = S("kafka:clusters", lambda: P(kf, "list_clusters_v2", "ClusterInfoList[]"))
    out["msk"] = [{"name": c.get("ClusterName"), "type": c.get("ClusterType"), "state": c.get("State"),
                   "version": ((c.get("Provisioned") or {}).get("CurrentBrokerSoftwareInfo") or {}).get("KafkaVersion"),
                   "brokers": (c.get("Provisioned") or {}).get("NumberOfBrokerNodes")} for c in msk]
    return out


# ═══ SEGURANÇA (regional) ════════════════════════════════════════════════════
def col_security(A, r):
    S = lambda name, fn, d=_NO, q=(): A.safe(r, name, fn, [] if d is _NO else d, quiet=q)
    out = {}
    acm = A.c("acm", r)
    certs = S("acm:list", lambda: P(acm, "list_certificates", "CertificateSummaryList[]",
                                    Includes={"keyTypes": ["RSA_1024", "RSA_2048", "RSA_3072", "RSA_4096", "EC_prime256v1", "EC_secp384r1", "EC_secp521r1"]}))
    crow = []
    for c in certs:
        d = S("acm:describe", lambda c=c: acm.describe_certificate(CertificateArn=c["CertificateArn"])["Certificate"], d={})
        crow.append({"arn": c["CertificateArn"], "domain": d.get("DomainName") or c.get("DomainName"), "status": d.get("Status"),
                     "type": d.get("Type"), "key": d.get("KeyAlgorithm"), "in_use": len(d.get("InUseBy", [])),
                     "in_use_by": [short_arn(x) for x in d.get("InUseBy", [])][:10], "expires": d.get("NotAfter"),
                     "renewal": d.get("RenewalEligibility"), "sans": d.get("SubjectAlternativeNames", [])[:30],
                     "validation": list({v.get("ValidationMethod") for v in d.get("DomainValidationOptions", []) if v.get("ValidationMethod")})})
    out["acm"] = crow

    kms = A.c("kms", r)
    aliases = S("kms:aliases", lambda: P(kms, "list_aliases", "Aliases[]"))
    amap = {}
    for a in aliases:
        if a.get("TargetKeyId"):
            amap.setdefault(a["TargetKeyId"], []).append(a["AliasName"])
    krows = []
    for k in S("kms:keys", lambda: P(kms, "list_keys", "Keys[]")):
        d = S("kms:describe", lambda k=k: kms.describe_key(KeyId=k["KeyId"])["KeyMetadata"], d={})
        if d.get("KeyManager") != "CUSTOMER":
            continue
        rot = None
        if d.get("KeySpec") == "SYMMETRIC_DEFAULT" and d.get("KeyState") == "Enabled" and d.get("Origin") == "AWS_KMS":
            rot = S("kms:rotation", lambda k=k: kms.get_key_rotation_status(KeyId=k["KeyId"]).get("KeyRotationEnabled"), d=None)
        krows.append({"id": k["KeyId"], "aliases": amap.get(k["KeyId"], []), "state": d.get("KeyState"), "spec": d.get("KeySpec"),
                      "usage": d.get("KeyUsage"), "rotation": rot, "multi_region": d.get("MultiRegion"),
                      "created": d.get("CreationDate"), "description": d.get("Description", "")})
    out["kms"] = krows

    sm = A.c("secretsmanager", r)
    secs = S("secretsmanager:list", lambda: P(sm, "list_secrets", "SecretList[]"))
    out["secrets"] = [{"name": s.get("Name"), "rotation": s.get("RotationEnabled", False), "last_rotated": s.get("LastRotatedDate"),
                       "last_accessed": s.get("LastAccessedDate"), "last_changed": s.get("LastChangedDate"),
                       "kms": bool(s.get("KmsKeyId")), "description": s.get("Description", "")} for s in secs]
    params = S("ssm:parameters", lambda: P(A.c("ssm", r), "describe_parameters", "Parameters[]"))
    out["ssm_parameters_summary"] = {"count": len(params),
                                     "by_type": {t: sum(1 for p in params if p.get("Type") == t) for t in ("String", "StringList", "SecureString")}}

    ct = A.c("cloudtrail", r)
    trails = S("cloudtrail:trails", lambda: ct.describe_trails(includeShadowTrails=False).get("trailList", []))
    trows = []
    for t in trails:
        st = S("cloudtrail:status", lambda t=t: ct.get_trail_status(Name=t["TrailARN"]), d={})
        trows.append({"name": t.get("Name"), "multi_region": t.get("IsMultiRegionTrail"), "org_trail": t.get("IsOrganizationTrail"),
                      "logging": st.get("IsLogging"), "bucket": t.get("S3BucketName"), "kms": bool(t.get("KmsKeyId")),
                      "log_validation": t.get("LogFileValidationEnabled"), "cw_logs": bool(t.get("CloudWatchLogsLogGroupArn")),
                      "last_delivery": st.get("LatestDeliveryTime")})
    out["cloudtrail"] = trows

    gd = A.c("guardduty", r)
    dets = S("guardduty:detectors", lambda: gd.list_detectors().get("DetectorIds", []))
    gdo = {"enabled": False}
    if dets:
        d = S("guardduty:detector", lambda: gd.get_detector(DetectorId=dets[0]), d={})
        gdo = {"enabled": d.get("Status") == "ENABLED", "detector": dets[0],
               "features": [f.get("Name") for f in d.get("Features", []) if f.get("Status") == "ENABLED"]}
        stats = S("guardduty:stats", lambda: gd.get_findings_statistics(
            DetectorId=dets[0], FindingStatisticTypes=["COUNT_BY_SEVERITY"],
            FindingCriteria={"Criterion": {"service.archived": {"Eq": ["false"]}}}).get("FindingStatistics", {}).get("CountBySeverity", {}), d={})
        sev = {"high": 0, "medium": 0, "low": 0}
        for k, v in (stats or {}).items():
            f = float(k)
            sev["high" if f >= 7 else "medium" if f >= 4 else "low"] += v
        gdo["findings"] = sev
    out["guardduty"] = gdo

    sh = A.c("securityhub", r)
    hub = S("securityhub:hub", lambda: sh.describe_hub(), d=None, q=("InvalidAccessException", "ResourceNotFoundException"))
    sho = {"enabled": bool(hub)}
    if hub:
        stds = S("securityhub:standards", lambda: sh.get_enabled_standards().get("StandardsSubscriptions", []))
        sho["standards"] = [(s.get("StandardsArn", "").split("/") + ["", ""])[1] for s in stds]
    out["securityhub"] = sho

    cfg = A.c("config", r)
    rec = S("config:recorder", lambda: cfg.describe_configuration_recorder_status().get("ConfigurationRecordersStatus", []))
    out["config"] = {"enabled": any(x.get("recording") for x in rec), "recorders": len(rec),
                     "last_status": rec[0].get("lastStatus") if rec else None}

    aa = A.c("accessanalyzer", r)
    an = S("accessanalyzer:list", lambda: P(aa, "list_analyzers", "analyzers[]"))
    out["access_analyzer"] = [{"name": a.get("name"), "type": a.get("type"), "status": a.get("status")} for a in an]

    waf = A.c("wafv2", r)
    acls = S("wafv2:regional", lambda: P(waf, "list_web_acls", "WebACLs[]", Scope="REGIONAL"))
    wrows = []
    for w in acls:
        res = S("wafv2:resources", lambda w=w: waf.list_resources_for_web_acl(WebACLArn=w["ARN"], ResourceType="APPLICATION_LOAD_BALANCER").get("ResourceArns", []))
        wrows.append({"name": w.get("Name"), "id": w.get("Id"), "scope": "REGIONAL", "albs": [a.split("/")[-2] for a in res]})
    out["waf"] = wrows
    return out


# ═══ OPERAÇÃO ════════════════════════════════════════════════════════════════
def col_operations(A, r):
    S = lambda name, fn, d=_NO, q=(): A.safe(r, name, fn, [] if d is _NO else d, quiet=q)
    out = {}
    cw = A.c("cloudwatch", r)
    alarms = S("cloudwatch:alarms", lambda: P(cw, "describe_alarms", "MetricAlarms[]"))
    out["cloudwatch_alarms"] = [{"name": a.get("AlarmName"), "state": a.get("StateValue"), "namespace": a.get("Namespace"),
                                 "metric": a.get("MetricName"), "actions": len(a.get("AlarmActions", [])),
                                 "enabled": a.get("ActionsEnabled"), "updated": a.get("StateUpdatedTimestamp")} for a in alarms]
    out["cloudwatch_dashboards"] = len(S("cloudwatch:dashboards", lambda: P(cw, "list_dashboards", "DashboardEntries[]")))
    logs = A.c("logs", r)
    lgs = S("logs:groups", lambda: P(logs, "describe_log_groups", "logGroups[]"))
    out["log_groups"] = [{"name": g.get("logGroupName"), "retention_days": g.get("retentionInDays"),
                          "stored_mb": round((g.get("storedBytes") or 0) / 1048576, 1), "kms": bool(g.get("kmsKeyId")),
                          "class": g.get("logGroupClass")} for g in lgs]
    bk = A.c("backup", r)
    plans = S("backup:plans", lambda: P(bk, "list_backup_plans", "BackupPlansList[]"))
    vaults = S("backup:vaults", lambda: P(bk, "list_backup_vaults", "BackupVaultList[]"))
    prot = S("backup:protected", lambda: P(bk, "list_protected_resources", "Results[]"))
    out["backup"] = {"plans": [{"name": p.get("BackupPlanName"), "id": p.get("BackupPlanId"), "last_run": p.get("LastExecutionDate")} for p in plans],
                     "vaults": [{"name": v.get("BackupVaultName"), "recovery_points": v.get("NumberOfRecoveryPoints"),
                                 "locked": v.get("Locked", False)} for v in vaults],
                     "protected_resources": len(prot),
                     "protected_by_type": {t: sum(1 for x in prot if x.get("ResourceType") == t) for t in {x.get("ResourceType") for x in prot}}}
    return out


REGIONAL = [
    ("network", col_network),
    ("connectivity", col_connectivity),
    ("compute", col_compute),
    ("loadbalancers", col_loadbalancers),
    ("serverless", col_serverless),
    ("containers", col_containers),
    ("data", col_data),
    ("security", col_security),
    ("operations", col_operations),
]


def collect_region(A, r):
    t0 = time.time()
    data = {}
    with ThreadPoolExecutor(max_workers=A.opts.inner_workers) as ex:
        futs = {ex.submit(fn, A, r): name for name, fn in REGIONAL}
        for f in as_completed(futs):
            name = futs[f]
            try:
                data.update(f.result() or {})
            except Exception as e:  # noqa: BLE001
                A.err(r, name, type(e).__name__, str(e))
    data["_elapsed_s"] = round(time.time() - t0, 1)
    return data


def region_has_resources(d):
    keys = ("vpcs", "ec2", "rds", "rds_clusters", "lambda", "ecs", "eks", "load_balancers", "dynamodb", "elasticache",
            "efs", "transit_gateways", "vpn_connections", "api_gateway", "sqs", "sns", "ecr", "acm", "secrets", "kms",
            "cloudwatch_alarms", "opensearch", "redshift", "fsx", "beanstalk", "asg", "ebs_volumes", "eips")
    for k in keys:
        v = d.get(k)
        if k == "vpcs":
            v = [x for x in (v or []) if not x.get("is_default") or x.get("enis")]
        if v:
            return True
    return False


# ═══ GLOBAIS ═════════════════════════════════════════════════════════════════
def col_iam(A):
    r = "global"
    iam = A.c("iam", "us-east-1")
    S = lambda name, fn, d=_NO, q=(): A.safe(r, name, fn, [] if d is _NO else d, quiet=q)
    out = {}
    out["account_summary"] = S("iam:account_summary", lambda: iam.get_account_summary()["SummaryMap"], d={})
    out["password_policy"] = S("iam:password_policy", lambda: iam.get_account_password_policy()["PasswordPolicy"], d=None,
                               q=("NoSuchEntity",))

    # relatório de credenciais (MFA, uso de senha e idade das chaves de todos os usuários + root)
    cred = []
    for _ in range(10):
        st = S("iam:credential_report", lambda: iam.generate_credential_report().get("State"), d=None)
        if st == "COMPLETE" or st is None:
            break
        time.sleep(2)
    raw = S("iam:credential_report", lambda: iam.get_credential_report()["Content"], d=None)
    if raw:
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8") if isinstance(raw, bytes) else raw)):
            cred.append(row)
    cmap = {c["user"]: c for c in cred}
    root = cmap.get("<root_account>", {})
    out["root"] = {"mfa": root.get("mfa_active") == "true",
                   "access_keys": (root.get("access_key_1_active") == "true") or (root.get("access_key_2_active") == "true"),
                   "password_last_used": root.get("password_last_used")}

    def nv(v):
        return None if v in (None, "", "N/A", "no_information", "not_supported") else v

    auth = {"UserDetailList": [], "GroupDetailList": [], "RoleDetailList": [], "Policies": []}
    try:
        for pg in iam.get_paginator("get_account_authorization_details").paginate(
                Filter=["User", "Role", "Group", "LocalManagedPolicy"]):
            for k in auth:
                auth[k] += pg.get(k, [])
    except Exception as e:  # noqa: BLE001
        A.err(r, "iam:authorization_details", type(e).__name__, str(e))

    group_pols = {g["GroupName"]: [p["PolicyName"] for p in g.get("AttachedManagedPolicies", [])] for g in auth["GroupDetailList"]}
    ADMIN = {"AdministratorAccess"}
    users = []
    for u in auth["UserDetailList"]:
        c = cmap.get(u["UserName"], {})
        direct = [p["PolicyName"] for p in u.get("AttachedManagedPolicies", [])]
        groups = u.get("GroupList", [])
        via_groups = [p for g in groups for p in group_pols.get(g, [])]
        keys = []
        for i in ("1", "2"):
            if c.get("access_key_%s_active" % i) == "true":
                keys.append({"age_days": days_since(nv(c.get("access_key_%s_last_rotated" % i))),
                             "last_used": nv(c.get("access_key_%s_last_used_date" % i))})
        users.append({
            "name": u["UserName"], "created": u.get("CreateDate"), "groups": groups, "policies": direct,
            "inline_policies": len(u.get("UserPolicyList", [])), "admin": bool(ADMIN & set(direct + via_groups)),
            "console": c.get("password_enabled") == "true", "mfa": c.get("mfa_active") == "true",
            "password_last_used": nv(c.get("password_last_used")), "access_keys": keys,
            "tags": tagmap(u.get("Tags")),
        })
    out["users"] = users
    out["groups"] = [{"name": g["GroupName"], "policies": group_pols.get(g["GroupName"], []),
                      "inline_policies": len(g.get("GroupPolicyList", [])),
                      "members": sum(1 for u in users if g["GroupName"] in u["groups"])} for g in auth["GroupDetailList"]]

    def principals(doc):
        out_p = []
        if isinstance(doc, str):
            try:
                doc = json.loads(doc)
            except ValueError:
                return out_p
        for st in (doc or {}).get("Statement", []):
            p = st.get("Principal", {})
            if isinstance(p, str):
                out_p.append(p)
                continue
            for k, v in p.items():
                for x in (v if isinstance(v, list) else [v]):
                    out_p.append("%s:%s" % (k, x))
        return out_p

    roles = []
    for ro in auth["RoleDetailList"]:
        if ro.get("Path", "/").startswith("/aws-service-role/") and not A.opts.include_service_roles:
            continue
        pols = [p["PolicyName"] for p in ro.get("AttachedManagedPolicies", [])]
        roles.append({"name": ro["RoleName"], "path": ro.get("Path"), "created": ro.get("CreateDate"),
                      "last_used": (ro.get("RoleLastUsed") or {}).get("LastUsedDate"),
                      "last_used_region": (ro.get("RoleLastUsed") or {}).get("Region"),
                      "trusted": principals(ro.get("AssumeRolePolicyDocument")), "policies": pols,
                      "inline_policies": len(ro.get("RolePolicyList", [])), "admin": bool(ADMIN & set(pols)),
                      "instance_profiles": [ip.get("InstanceProfileName") for ip in ro.get("InstanceProfileList", [])]})
    out["roles"] = roles
    out["customer_policies"] = [{"name": p.get("PolicyName"), "attachments": p.get("AttachmentCount", 0), "created": p.get("CreateDate"),
                                 "updated": p.get("UpdateDate")} for p in auth["Policies"]]
    out["saml_providers"] = [short_arn(p.get("Arn")) for p in S("iam:saml", lambda: iam.list_saml_providers().get("SAMLProviderList", []))]
    out["oidc_providers"] = [p.get("Arn", "").split("/", 1)[-1] for p in S("iam:oidc", lambda: iam.list_open_id_connect_providers().get("OpenIDConnectProviderList", []))]
    return out


def col_s3(A):
    r = "global"
    s3 = A.c("s3", "us-east-1")
    S = lambda name, fn, d=_NO, q=(): A.safe(r, name, fn, [] if d is _NO else d, quiet=q)
    buckets = S("s3:list", lambda: s3.list_buckets().get("Buckets", []))

    def one(b):
        n = b["Name"]
        loc = S("s3:location", lambda: s3.get_bucket_location(Bucket=n).get("LocationConstraint"), d=None)
        reg = loc or "us-east-1"
        if reg == "EU":
            reg = "eu-west-1"
        c = A.c("s3", reg)
        pab = S("s3:pab", lambda: c.get_public_access_block(Bucket=n)["PublicAccessBlockConfiguration"], d=None,
                q=("NoSuchPublicAccessBlockConfiguration",))
        pol_public = S("s3:policy_status", lambda: c.get_bucket_policy_status(Bucket=n)["PolicyStatus"].get("IsPublic"), d=False,
                       q=("NoSuchBucketPolicy",))
        enc = S("s3:encryption", lambda: c.get_bucket_encryption(Bucket=n)["ServerSideEncryptionConfiguration"]["Rules"][0]
                ["ApplyServerSideEncryptionByDefault"].get("SSEAlgorithm"), d=None,
                q=("ServerSideEncryptionConfigurationNotFoundError",))
        ver = S("s3:versioning", lambda: c.get_bucket_versioning(Bucket=n).get("Status", "Disabled"), d=None)
        lc = S("s3:lifecycle", lambda: bool(c.get_bucket_lifecycle_configuration(Bucket=n).get("Rules")), d=False,
               q=("NoSuchLifecycleConfiguration",))
        logging_on = S("s3:logging", lambda: bool(c.get_bucket_logging(Bucket=n).get("LoggingEnabled")), d=False)
        size = objs = None
        if not A.opts.no_s3_metrics:
            cw = A.c("cloudwatch", reg)
            now = dt.datetime.now(dt.timezone.utc)
            def metric(mname, stype):
                dps = cw.get_metric_statistics(Namespace="AWS/S3", MetricName=mname,
                                               Dimensions=[{"Name": "BucketName", "Value": n}, {"Name": "StorageType", "Value": stype}],
                                               StartTime=now - dt.timedelta(days=3), EndTime=now, Period=86400,
                                               Statistics=["Average"]).get("Datapoints", [])
                return max(dps, key=lambda x: x["Timestamp"])["Average"] if dps else None
            size = S("cloudwatch:s3_size", lambda: metric("BucketSizeBytes", "StandardStorage"), d=None)
            objs = S("cloudwatch:s3_objects", lambda: metric("NumberOfObjects", "AllStorageTypes"), d=None)
        blocked = bool(pab) and all(pab.get(k) for k in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"))
        return {"name": n, "region": reg, "created": b.get("CreationDate"), "versioning": ver, "encryption": enc,
                "public_access_blocked": blocked, "policy_public": bool(pol_public), "lifecycle": lc, "logging": logging_on,
                "size_gb": round(size / 1073741824, 2) if size is not None else None,
                "objects": int(objs) if objs is not None else None}

    rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for f in as_completed([ex.submit(one, b) for b in buckets]):
            try:
                rows.append(f.result())
            except Exception as e:  # noqa: BLE001
                A.err(r, "s3:bucket", type(e).__name__, str(e))
    rows.sort(key=lambda x: x["name"])
    return rows


def col_route53(A):
    r = "global"
    r53 = A.c("route53", "us-east-1")
    S = lambda name, fn, d=_NO, q=(): A.safe(r, name, fn, [] if d is _NO else d, quiet=q)
    zones = S("route53:zones", lambda: P(r53, "list_hosted_zones", "HostedZones[]"))
    out = []
    for z in zones:
        zid = z["Id"].split("/")[-1]
        recs = S("route53:records", lambda zid=zid: P(r53, "list_resource_record_sets", "ResourceRecordSets[]", HostedZoneId=zid))
        vpcs = []
        if z.get("Config", {}).get("PrivateZone"):
            vpcs = S("route53:zone_vpcs", lambda zid=zid: ["%s (%s)" % (v.get("VPCId"), v.get("VPCRegion"))
                                                          for v in r53.get_hosted_zone(Id=zid).get("VPCs", [])])
        out.append({"id": zid, "name": z["Name"].rstrip("."), "private": z.get("Config", {}).get("PrivateZone", False),
                    "comment": z.get("Config", {}).get("Comment", ""), "record_count": z.get("ResourceRecordSetCount"),
                    "vpcs": vpcs,
                    "records": [{"name": x["Name"].rstrip("."), "type": x["Type"], "ttl": x.get("TTL"),
                                 "values": [v["Value"] for v in x.get("ResourceRecords", [])][:8],
                                 "alias": (x.get("AliasTarget") or {}).get("DNSName", "").rstrip(".") or None,
                                 "routing": "weighted" if "Weight" in x else "latency" if "Region" in x else "failover" if "Failover" in x else None}
                                for x in recs[:A.opts.max_records]]})
    hcs = S("route53:health_checks", lambda: P(r53, "list_health_checks", "HealthChecks[]"))
    return {"zones": out, "health_checks": [{"id": h["Id"], "type": h.get("HealthCheckConfig", {}).get("Type"),
                                             "target": h.get("HealthCheckConfig", {}).get("FullyQualifiedDomainName")
                                             or h.get("HealthCheckConfig", {}).get("IPAddress")} for h in hcs]}


def col_cloudfront(A):
    r = "global"
    cf = A.c("cloudfront", "us-east-1")
    S = lambda name, fn, d=_NO: A.safe(r, name, fn, [] if d is _NO else d)
    ds = S("cloudfront:distributions", lambda: P(cf, "list_distributions", "DistributionList.Items[]"))
    rows = [{
        "id": d["Id"], "domain": d.get("DomainName"), "aliases": (d.get("Aliases") or {}).get("Items", []),
        "enabled": d.get("Enabled"), "status": d.get("Status"), "price_class": d.get("PriceClass"),
        "origins": [o.get("DomainName") for o in (d.get("Origins") or {}).get("Items", [])],
        "waf": short_arn(d.get("WebACLId")) or None, "http_version": d.get("HttpVersion"),
        "viewer_protocol": (d.get("DefaultCacheBehavior") or {}).get("ViewerProtocolPolicy"),
        "min_tls": (d.get("ViewerCertificate") or {}).get("MinimumProtocolVersion"),
        "comment": d.get("Comment", ""),
    } for d in ds]
    waf = A.c("wafv2", "us-east-1")
    acls = S("wafv2:cloudfront", lambda: P(waf, "list_web_acls", "WebACLs[]", Scope="CLOUDFRONT"))
    return rows, [{"name": w.get("Name"), "id": w.get("Id"), "scope": "CLOUDFRONT"} for w in acls]


def col_cost(A):
    r = "global"
    ce = A.c("ce", "us-east-1")
    S = lambda name, fn, d=_NO: A.safe(r, name, fn, [] if d is _NO else d)
    today = dt.date.today()
    first = today.replace(day=1)
    start = (first - dt.timedelta(days=95)).replace(day=1)
    out = {"currency": "USD", "months": [], "by_service": {}, "by_region_last_month": {}, "mtd": None, "forecast": None}
    res = S("ce:by_service", lambda: ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": first.isoformat()}, Granularity="MONTHLY",
        Metrics=["UnblendedCost"], GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}]).get("ResultsByTime", []))
    for p in res:
        m = p["TimePeriod"]["Start"][:7]
        out["months"].append(m)
        for g in p.get("Groups", []):
            amt = float(g["Metrics"]["UnblendedCost"]["Amount"])
            if abs(amt) >= 0.01:
                out["by_service"].setdefault(g["Keys"][0], {})[m] = round(amt, 2)
    last_start = (first - dt.timedelta(days=1)).replace(day=1)
    rr = S("ce:by_region", lambda: ce.get_cost_and_usage(
        TimePeriod={"Start": last_start.isoformat(), "End": first.isoformat()}, Granularity="MONTHLY",
        Metrics=["UnblendedCost"], GroupBy=[{"Type": "DIMENSION", "Key": "REGION"}]).get("ResultsByTime", []))
    for p in rr:
        for g in p.get("Groups", []):
            amt = float(g["Metrics"]["UnblendedCost"]["Amount"])
            if abs(amt) >= 0.01:
                out["by_region_last_month"][g["Keys"][0] or "global"] = round(amt, 2)
    if today.day > 1:
        mtd = S("ce:mtd", lambda: ce.get_cost_and_usage(
            TimePeriod={"Start": first.isoformat(), "End": today.isoformat()}, Granularity="MONTHLY",
            Metrics=["UnblendedCost"]).get("ResultsByTime", []))
        if mtd:
            out["mtd"] = round(float(mtd[0]["Total"]["UnblendedCost"]["Amount"]), 2)
    return out


def col_finops(A):
    """Recomendações FinOps (Compute Optimizer, Cost Explorer) e riscos do Well-Architected Tool."""
    out = {"compute_optimizer": {"ec2": [], "ebs": [], "lambda": []}, "savings_plans": None, "well_architected": []}
    home = A.opts.home_region or "us-east-1"
    quiet_co = ("OptInRequiredException", "AccessDeniedException", "InvalidInputException")

    co = A.c("compute-optimizer", home)
    ec2_recs = A.safe(home, "co:ec2", lambda: co.get_ec2_instance_recommendations(maxResults=100).get("instanceRecommendations", []), [], quiet=quiet_co)
    for r in ec2_recs:
        if r.get("finding") not in ("OVER_PROVISIONED", "UNDER_PROVISIONED"):
            continue
        opts = r.get("recommendationOptions") or []
        best = opts[0] if opts else {}
        sav = (best.get("estimatedMonthlySavings") or {})
        out["compute_optimizer"]["ec2"].append({
            "id": (r.get("instanceArn") or "").split("/")[-1],
            "name": r.get("instanceName") or "",
            "finding": r.get("finding"),
            "current": r.get("currentInstanceType"),
            "recommended": best.get("instanceType"),
            "savings_usd": round(float(sav.get("value", 0) or 0), 2),
        })

    ebs_recs = A.safe(home, "co:ebs", lambda: co.get_ebs_volume_recommendations(maxResults=100).get("volumeRecommendations", []), [], quiet=quiet_co)
    for r in ebs_recs:
        if r.get("finding") != "NotOptimized":
            continue
        cur = r.get("currentConfiguration") or {}
        opts = r.get("volumeRecommendationOptions") or []
        best = opts[0] if opts else {}
        cfg = best.get("configuration") or {}
        sav = best.get("estimatedMonthlySavings") or {}
        out["compute_optimizer"]["ebs"].append({
            "id": (r.get("volumeArn") or "").split("/")[-1],
            "current": f"{cur.get('volumeType', '')} {cur.get('volumeSize', '')}GB",
            "recommended": f"{cfg.get('volumeType', '')} {cfg.get('volumeSize', '')}GB",
            "savings_usd": round(float(sav.get("value", 0) or 0), 2),
        })

    lmb_recs = A.safe(home, "co:lambda", lambda: co.get_lambda_function_recommendations(maxResults=100).get("lambdaFunctionRecommendations", []), [], quiet=quiet_co)
    for r in lmb_recs:
        if r.get("finding") != "NotOptimized":
            continue
        opts = r.get("memorySizeRecommendationOptions") or []
        best = opts[0] if opts else {}
        sav = best.get("estimatedMonthlySavings") or {}
        out["compute_optimizer"]["lambda"].append({
            "id": (r.get("functionArn") or "").split(":")[-2] if ":" in (r.get("functionArn") or "") else r.get("functionArn"),
            "current_mb": r.get("currentMemorySize"),
            "recommended_mb": best.get("memorySize"),
            "savings_usd": round(float(sav.get("value", 0) or 0), 2),
        })

    if not A.opts.no_cost:
        ce = A.c("ce", "us-east-1")
        sp = A.safe("global", "ce:sp_rec", lambda: ce.get_savings_plans_purchase_recommendation(
            SavingsPlansType="COMPUTE_SP", TermInYears="ONE_YEAR", PaymentOption="NO_UPFRONT", LookbackPeriodInDays="THIRTY_DAYS"
        ).get("SavingsPlansPurchaseRecommendation", {}), None, quiet=("DataUnavailableException", "AccessDeniedException"))
        if sp and sp.get("SavingsPlansPurchaseRecommendationSummary"):
            s = sp["SavingsPlansPurchaseRecommendationSummary"]
            out["savings_plans"] = {
                "type": "COMPUTE_SP (1 ano, No Upfront)",
                "estimated_monthly_savings_usd": round(float(s.get("EstimatedMonthlySavingsAmount", 0) or 0), 2),
                "estimated_savings_pct": round(float(s.get("EstimatedSavingsPercentage", 0) or 0), 1),
                "hourly_commitment": s.get("HourlyCommitmentToPurchase"),
            }

    wa = A.c("wellarchitected", home)
    wls = A.safe(home, "wa:workloads", lambda: wa.list_workloads(MaxResults=20).get("WorkloadSummaries", []), [],
                 quiet=("AccessDeniedException", "ValidationException"))
    for w in wls[:10]:
        wid = w.get("WorkloadId")
        if not wid:
            continue
        revs = A.safe(home, "wa:reviews", lambda wid=wid: wa.list_lens_reviews(WorkloadId=wid).get("LensReviewSummaries", []), [],
                      quiet=("AccessDeniedException", "ResourceNotFoundException"))
        for rv in revs:
            rc = rv.get("RiskCounts") or {}
            if rc.get("HIGH", 0) or rc.get("MEDIUM", 0):
                out["well_architected"].append({
                    "workload": w.get("WorkloadName"),
                    "lens": rv.get("LensAlias"),
                    "high": rc.get("HIGH", 0),
                    "medium": rc.get("MEDIUM", 0),
                })
    return out


def col_globals(A):
    g = {}

    def step(label, key, fn, default):
        say(DIM("  · " + label))
        try:
            g[key] = fn(A)
        except Exception as e:  # noqa: BLE001 — um bloco global com falha não derruba a coleta
            A.err("global", key, type(e).__name__, str(e))
            g[key] = default

    step("IAM / credenciais", "iam", col_iam, {})
    step("S3", "s3", col_s3, [])
    step("Route 53", "route53", col_route53, {"zones": [], "health_checks": []})
    step("CloudFront / WAF global", "_cf", col_cloudfront, ([], []))
    g["cloudfront"], g["waf_cloudfront"] = g.pop("_cf")
    s3c = A.c("s3control", "us-east-1")
    g["s3_account_public_block"] = A.safe("global", "s3control:pab", lambda: all(
        s3c.get_public_access_block(AccountId=A.account_id)["PublicAccessBlockConfiguration"].values()), None,
        quiet=("NoSuchPublicAccessBlockConfiguration",))
    org = A.c("organizations", "us-east-1")
    o = A.safe("global", "organizations:describe", lambda: org.describe_organization()["Organization"], None,
               quiet=("AWSOrganizationsNotInUseException", "AccessDeniedException"))
    g["organization"] = None
    if o:
        g["organization"] = {"id": o.get("Id"), "management_account": o.get("MasterAccountId"),
                             "is_management": o.get("MasterAccountId") == A.account_id, "feature_set": o.get("FeatureSet")}
        if g["organization"]["is_management"]:
            accs = A.safe("global", "organizations:accounts", lambda: P(org, "list_accounts", "Accounts[]"), [])
            g["organization"]["accounts"] = [{"id": a["Id"], "name": a.get("Name"), "email": a.get("Email"), "status": a.get("Status")} for a in accs]
    bud = A.c("budgets", "us-east-1")
    bl = A.safe("global", "budgets:list", lambda: P(bud, "describe_budgets", "Budgets[]", AccountId=A.account_id), [],
                quiet=("NotFoundException",))
    g["budgets"] = [{"name": b.get("BudgetName"), "type": b.get("BudgetType"), "period": b.get("TimeUnit"),
                     "limit": float((b.get("BudgetLimit") or {}).get("Amount", 0) or 0),
                     "actual": float(((b.get("CalculatedSpend") or {}).get("ActualSpend") or {}).get("Amount", 0) or 0),
                     "forecast": float(((b.get("CalculatedSpend") or {}).get("ForecastedSpend") or {}).get("Amount", 0) or 0)} for b in bl]
    if not A.opts.no_cost:
        step("Cost Explorer", "cost", col_cost, None)
    step("FinOps / Well-Architected", "finops", col_finops, {})
    return g


# ═══ ORQUESTRAÇÃO ════════════════════════════════════════════════════════════
def collect_account(session, opts, alias_hint=None):
    t0 = time.time()
    sts = session.client("sts", config=CFG)
    ident = sts.get_caller_identity()
    acct = ident["Account"]
    A = Account(session, opts, alias_hint or acct)
    A.account_id = acct
    iam = A.c("iam", "us-east-1")
    iam_aliases = A.safe("global", "iam:aliases", lambda: iam.list_account_aliases().get("AccountAliases", []), [])
    alias = alias_hint or (iam_aliases[0] if iam_aliases else acct)

    say("")
    say(BOLD(CYAN("▸ Conta %s  (%s)" % (alias, acct))))
    say(DIM("  Identidade: %s" % ident["Arn"]))

    ec2 = A.c("ec2", opts.home_region)
    enabled = sorted(r["RegionName"] for r in ec2.describe_regions(AllRegions=False)["Regions"])
    regions = [r for r in enabled if not opts.regions or r in opts.regions]
    say(DIM("  %d regiões habilitadas, %d serão varridas" % (len(enabled), len(regions))))

    say(DIM("  Serviços globais:"))
    glob = col_globals(A)

    say(DIM("  Regiões:"))
    reg_data, done, sec_status = {}, [0], {}
    with ThreadPoolExecutor(max_workers=opts.workers) as ex:
        futs = {ex.submit(collect_region, A, r): r for r in regions}
        for f in as_completed(futs):
            r = futs[f]
            try:
                d = f.result()
            except Exception as e:  # noqa: BLE001
                A.err(r, "region", type(e).__name__, str(e))
                continue
            done[0] += 1
            sec_status[r] = {"guardduty": (d.get("guardduty") or {}).get("enabled", False),
                             "securityhub": (d.get("securityhub") or {}).get("enabled", False),
                             "config": (d.get("config") or {}).get("enabled", False),
                             "access_analyzer": bool(d.get("access_analyzer")),
                             "cloudtrail_home": bool(d.get("cloudtrail"))}
            used = region_has_resources(d)
            if used or opts.keep_empty:
                reg_data[r] = d
            mark = GREEN("●") if used else DIM("○")
            summary = ", ".join("%s %d" % (k, len(d.get(k) or [])) for k in ("vpcs", "ec2", "rds", "lambda", "ecs", "load_balancers")
                                if d.get(k)) or "sem recursos"
            say("    %s %-16s %s  %s" % (mark, r, DIM("%5.1fs" % d.get("_elapsed_s", 0)), summary if used else DIM(summary)))

    elapsed = round(time.time() - t0, 1)
    payload = {
        "schema": SCHEMA,
        "collector_version": VERSION,
        "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "duration_s": elapsed,
        "account": {
            "id": acct, "alias": alias, "iam_aliases": iam_aliases, "caller_arn": ident["Arn"],
            "regions_enabled": enabled, "regions_scanned": regions, "regions_with_resources": sorted(reg_data),
            "home_region": opts.home_region,
        },
        "global": glob,
        "regions": dict(sorted(reg_data.items())),
        "regions_security": dict(sorted(sec_status.items())),
        "errors": A.errors,
    }
    n_err = len([e for e in A.errors if e["code"] not in ("OptInRequired",)])
    say(GREEN("  ✓ concluído em %ss — %d regiões com recursos, %d avisos de permissão/erro" % (elapsed, len(reg_data), n_err)))
    return payload


def write_json(obj, path, gz):
    data = json.dumps(obj, default=iso, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if gz or path.endswith(".gz"):
        if not path.endswith(".gz"):
            path += ".gz"
        with gzip.open(path, "wb", compresslevel=9) as f:
            f.write(data)
    else:
        with open(path, "wb") as f:
            f.write(data)
    return path, os.path.getsize(path)


def load_any(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def cmd_merge(argv):
    ap = argparse.ArgumentParser(prog="docviva_collector.py merge", description="Consolida arquivos de várias contas num único bundle.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out", default="docviva_bundle_%s.json" % dt.date.today().strftime("%Y%m%d"))
    ap.add_argument("--gzip", action="store_true")
    a = ap.parse_args(argv)
    accounts = []
    for p in a.files:
        d = load_any(p)
        if d.get("schema") == BUNDLE_SCHEMA:
            accounts += d.get("accounts", [])
        elif d.get("schema") == SCHEMA:
            accounts.append(d)
        else:
            say(YELLOW("  ! %s não está no formato docviva/2 — importe-o direto no DocViva (formato legado)." % p))
    seen = {}
    for acc in accounts:  # se a mesma conta vier duas vezes, fica a coleta mais recente
        k = acc["account"]["id"]
        if k not in seen or acc["collected_at"] > seen[k]["collected_at"]:
            seen[k] = acc
    bundle = {"schema": BUNDLE_SCHEMA, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "collector_version": VERSION, "accounts": sorted(seen.values(), key=lambda x: x["account"]["alias"])}
    path, size = write_json(bundle, a.out, a.gzip)
    say(GREEN("✓ Bundle com %d conta(s): %s (%.1f MB)" % (len(seen), path, size / 1048576)))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "merge":
        return cmd_merge(sys.argv[2:])

    ap = argparse.ArgumentParser(description="DocViva Collector v2 — inventário AWS completo, somente leitura.")
    ap.add_argument("--alias", help="Nome amigável da conta (padrão: alias do IAM ou ID)")
    ap.add_argument("--profile", nargs="*", help="Um ou mais profiles do AWS CLI (cada um = uma conta)")
    ap.add_argument("--assume-role", nargs="*", metavar="ROLE_ARN", help="Roles a assumir (cada uma = uma conta)")
    ap.add_argument("--external-id", help="ExternalId para o AssumeRole, se exigido")
    ap.add_argument("--regions", nargs="*", help="Restringe a estas regiões (padrão: todas as habilitadas)")
    ap.add_argument("--home-region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1")
    ap.add_argument("-o", "--out", help="Arquivo de saída")
    ap.add_argument("--gzip", action="store_true", help="Compacta a saída (.json.gz) — o DocViva importa direto")
    ap.add_argument("--workers", type=int, default=6, help="Regiões em paralelo (padrão 6)")
    ap.add_argument("--inner-workers", type=int, default=4, help="Grupos de serviço em paralelo por região (padrão 4)")
    ap.add_argument("--no-cost", action="store_true", help="Não consulta o Cost Explorer (US$ 0,01 por consulta)")
    ap.add_argument("--no-s3-metrics", action="store_true", help="Não busca tamanho/objetos dos buckets no CloudWatch")
    ap.add_argument("--keep-empty", action="store_true", help="Mantém no arquivo regiões sem recursos")
    ap.add_argument("--include-service-roles", action="store_true", help="Inclui roles /aws-service-role/ na lista do IAM")
    ap.add_argument("--max-records", type=int, default=3000, help="Máximo de registros DNS guardados por zona")
    opts = ap.parse_args()

    say(BOLD("DocViva Collector v%s" % VERSION) + DIM("  — somente leitura"))

    targets = []  # (session, alias_hint)
    base = boto3.Session()
    if opts.assume_role:
        sts = base.client("sts", config=CFG)
        for arn in opts.assume_role:
            kw = {"RoleArn": arn, "RoleSessionName": "docviva-collector", "DurationSeconds": 3600}
            if opts.external_id:
                kw["ExternalId"] = opts.external_id
            try:
                cr = sts.assume_role(**kw)["Credentials"]
            except ClientError as e:
                say(RED("  ✗ Não foi possível assumir %s: %s" % (arn, e)))
                continue
            targets.append((boto3.Session(aws_access_key_id=cr["AccessKeyId"], aws_secret_access_key=cr["SecretAccessKey"],
                                          aws_session_token=cr["SessionToken"]), None))
    elif opts.profile:
        targets = [(boto3.Session(profile_name=p), None) for p in opts.profile]
    else:
        targets = [(base, opts.alias)]

    payloads = []
    for sess, hint in targets:
        try:
            payloads.append(collect_account(sess, opts, hint))
        except NoCredentialsError:
            say(RED("  ✗ Sem credenciais. Rode no CloudShell ou configure um profile."))
        except ClientError as e:
            say(RED("  ✗ Falha ao iniciar a coleta: %s" % e))

    if not payloads:
        sys.exit(1)

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    if len(payloads) == 1:
        p = payloads[0]
        out = opts.out or "docviva_%s_%s_%s.json" % (re.sub(r"[^A-Za-z0-9_-]+", "-", p["account"]["alias"]), p["account"]["id"], stamp)
        obj = p
    else:
        out = opts.out or "docviva_bundle_%s.json" % stamp
        obj = {"schema": BUNDLE_SCHEMA, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
               "collector_version": VERSION, "accounts": payloads}
    path, size = write_json(obj, out, opts.gzip)
    say("")
    say(BOLD(GREEN("✓ Arquivo gerado: %s  (%.1f MB)" % (path, size / 1048576))))
    say(DIM("  Importe no DocViva. Para juntar contas coletadas separadamente:"))
    say(DIM("  python3 %s merge docviva_*.json -o docviva_bundle.json" % os.path.basename(sys.argv[0])))


if __name__ == "__main__":
    main()
