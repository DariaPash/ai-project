"""Known-URL HTTPS import, deny by default. Never a discovery/crawler adapter.

The production CLI has no injectable transport. Private test seams are exercised
with doubles, not evidence of a live TLS connection. A killed worker enforces the
whole DNS/headers/body deadline, in addition to socket/read and byte caps.
"""

import base64
import http.client
import ipaddress
import os
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import urljoin, urlsplit

from .contracts import digest, key, sha, validate_schema
from .errors import CoreError
from .records import RecordBatch
from .safeio import canonical, parse_json
from .sources import parse_snapshot, parser_profile, stage_source
from .store import now, unknown_usage


def checked_url(url, rules):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in url):
        raise CoreError("URL_UNSAFE", "Use a bounded ASCII HTTPS URL (IDNA hostname)", 4)
    try:
        value = urlsplit(url)
        host = (value.hostname or "").encode("idna").decode("ascii").lower()
        port = value.port
    except (UnicodeError, ValueError) as exc:
        raise CoreError("URL_UNSAFE", "Malformed hostname/port", 4) from exc
    path = value.path or "/"
    if (
        value.scheme != "https"
        or port not in (None, 443)
        or value.username is not None
        or value.password is not None
        or value.query
        or value.fragment
        or host.endswith(".")
        or "\\" in url
        or "%" in url
        or "//" in path
        or any(p in {".", ".."} for p in path.split("/"))
    ):
        raise CoreError("URL_UNSAFE", "Only HTTPS:443 without credentials, queries, fragments or ambiguous paths", 4)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise CoreError("URL_IP_LITERAL", "Use an explicitly allowlisted DNS hostname, not an IP literal", 4)
    if not host or not any(
        isinstance(rule, dict) and rule.get("host") == host and path in rule.get("paths", []) for rule in rules
    ):
        raise CoreError("DOMAIN_DENIED", "Exact hostname/path is not allowlisted", 4)
    return "https://" + host + path, host, path


def public_addresses(addresses):
    result = []
    if not addresses:
        raise CoreError("DNS_EMPTY", "DNS returned no usable addresses", 5)
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
        except ValueError as exc:
            raise CoreError("DNS_INVALID", "Invalid numeric DNS result", 4) from exc
        if not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_reserved or getattr(ip, "scope_id", None):
            raise CoreError("DNS_PRIVATE", "Every DNS answer must be global; mixed answers are rejected", 4)
        if isinstance(ip, ipaddress.IPv6Address) and any(
            ip in ipaddress.IPv6Network(prefix)
            for prefix in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
        ):
            raise CoreError("DNS_TRANSITION", "IPv6 transition/translation prefixes are not supported", 4)
        if str(ip) not in result:
            result.append(str(ip))
    return result


def _resolve(host):
    return [item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CoreError("FETCH_TIMEOUT", "Fetch exceeded its total deadline; no automatic retry", 5)
    return remaining


def _request(host, path, ip, limits, deadline):
    # Numeric tuple + socket.connect: no create_connection and no implicit DNS.
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    raw = socket.socket(family, socket.SOCK_STREAM)
    connection = raw
    try:
        raw.settimeout(min(_remaining(deadline), limits["connect_timeout_ms"] / 1000))
        raw.connect((ip, 443))
        context = ssl.create_default_context()
        connection = context.wrap_socket(raw, server_hostname=host)
        peer = str(ipaddress.ip_address(connection.getpeername()[0]))
        if peer != ip:
            raise CoreError("PEER_MISMATCH", "Connected peer differs from the pinned numeric IP", 4)
        connection.settimeout(_remaining(deadline))
        connection.sendall(
            (
                f"GET {path} HTTP/1.1\r\nHost: {host}\r\nAccept: text/html, application/xhtml+xml\r\nAccept-Encoding: identity\r\nConnection: close\r\nUser-Agent: evidence-local-import/1\r\n\r\n"
            ).encode("ascii")
        )
        response = http.client.HTTPResponse(connection)
        response.begin()  # stdlib line/count caps; parent worker also caps total time.
        headers = {}
        for name in ("Location", "Content-Type", "Content-Length", "Content-Encoding"):
            values = response.headers.get_all(name, [])
            if len(values) > 1:
                raise CoreError("HTTP_HEADERS", "Ambiguous duplicate response headers", 4)
            headers[name.lower()] = values[0] if values else ""
        metadata = {
            "peer_ip": peer,
            "tls_sni": host,
            "http_host": host,
            "certificate_verified": True,
            "certificate_sha256": sha(connection.getpeercert(binary_form=True)),
            "tls_version": connection.version(),
        }
        if response.status in {301, 302, 303, 307, 308}:
            return response.status, headers, b"", metadata
        if headers["content-encoding"].lower() not in {"", "identity"}:
            raise CoreError("HTTP_ENCODING", "Unexpected compression is not decoded", 4)
        if headers["content-length"] and (
            not headers["content-length"].isdigit() or int(headers["content-length"]) > limits["max_bytes"]
        ):
            raise CoreError("FETCH_BYTES", "Advertised response exceeds byte cap or is invalid", 4)
        chunks, size = [], 0
        while True:
            connection.settimeout(_remaining(deadline))
            chunk = response.read1(min(65536, limits["max_bytes"] - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > limits["max_bytes"]:
                raise CoreError("FETCH_BYTES", "Stream exceeded its byte cap", 4)
            chunks.append(chunk)
        if headers["content-length"] and size != int(headers["content-length"]):
            raise CoreError("HTTP_TRUNCATED", "Response length differs from its declaration", 5)
        return response.status, headers, b"".join(chunks), metadata
    finally:
        connection.close()
        raw.close()


def _download(url, rules, limits, *, _resolver=_resolve, _transport=_request):
    """Internal pure orchestration seam; never exposed by CLI/spec/config."""
    deadline = time.monotonic() + limits["timeout_ms"] / 1000
    visited, chain = set(), []
    for hop in range(limits["max_hops"] + 1):
        current, host, path = checked_url(url, rules)
        if current in visited:
            raise CoreError("REDIRECT_CYCLE", "Redirect cycle rejected", 4)
        visited.add(current)
        ips = public_addresses(_resolver(host))
        _remaining(deadline)
        status, headers, raw, metadata = _transport(host, path, ips[0], limits, deadline)
        _remaining(deadline)
        if (
            metadata.get("peer_ip") != ips[0]
            or metadata.get("certificate_verified") is not True
            or metadata.get("tls_sni") != host
            or metadata.get("http_host") != host
        ):
            raise CoreError("TLS_IDENTITY", "TLS/Host/peer verification was not established", 4)
        chain.append({"url": current, "dns_answers": ips, "selected_ip": ips[0], "status": status, **metadata})
        if status in {301, 302, 303, 307, 308}:
            if hop == limits["max_hops"] or not headers.get("location"):
                raise CoreError("REDIRECT_LIMIT", "Redirect missing a target or exceeded hop cap", 4)
            url = urljoin(current, headers["location"])
            continue
        if status != 200:
            raise CoreError("HTTP_STATUS", "URL did not return HTTP 200; no auth/paywall bypass", 3)
        mime = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime not in limits["allowed_mime"] or headers.get("content-encoding", "").lower() not in {"", "identity"}:
            raise CoreError("HTTP_CONTENT", "Response MIME/encoding is not permitted", 4)
        if not raw or len(raw) > limits["max_bytes"]:
            raise CoreError("FETCH_BYTES", "Response empty or over byte cap", 4)
        return raw, {
            "requested_url": next(iter(visited)) if len(visited) == 1 else chain[0]["url"],
            "final_url": current,
            "mime_type": mime,
            "sha256": sha(raw),
            "size": len(raw),
            "retrieved_at": now(),
            "redirect_chain": chain,
            "discovery_performed": False,
        }
    raise CoreError("REDIRECT_LIMIT", "Redirect cap reached", 4)


def download(url, rules, limits):
    request = canonical({"url": url, "rules": rules, "limits": limits})
    process = subprocess.Popen(
        [sys.executable, "-m", "tools.fetch_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        output, _ = process.communicate(request, timeout=limits["timeout_ms"] / 1000 + 0.5)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise CoreError("FETCH_TIMEOUT", "Fetch worker exceeded the bounded total deadline", 5) from exc
    if len(output) > 12 * 1024 * 1024 or not output:
        raise CoreError("FETCH_WORKER", "Fetch worker produced no bounded receipt", 5)
    receipt = parse_json(output)
    if not receipt["ok"]:
        raise CoreError(receipt["code"], receipt["reason"], receipt["exit"])
    return base64.b64decode(receipt["raw_base64"], validate=True), receipt["metadata"]


def _authorization(store, snapshot, records, url, spec):
    policy = store.io.json("config/source_policy.json")
    if policy.get("schema_version") != 1:
        raise CoreError("SOURCE_POLICY_VERSION", "Unknown source policy", 4)
    canonical_url, _, _ = checked_url(url, policy["allowed_domains"])
    ar, pr = spec["source_access_approval_ref"], spec["permission_ref"]
    if any(
        r["case_id"] != store.case_id
        or key(r) not in records
        or snapshot["active"].get(r["entity_id"]) != r["revision"]
        for r in (ar, pr)
    ):
        raise CoreError("FETCH_APPROVAL", "Fetch requires current pinned source/resource permission refs", 3)
    approval, permission = records[key(ar)], records[key(pr)]
    if approval["kind"] != "approval" or permission["kind"] != "permission":
        raise CoreError("FETCH_APPROVAL", "Incorrect approval/permission record kinds", 3)
    a, p = approval["payload"], permission["payload"]
    terms = a.get("terms", {})
    resource_approval = records[key(p["approval_ref"])]["payload"]
    from datetime import datetime, timezone

    try:
        expiry = datetime.fromisoformat(terms.get("expires_at", "").replace("Z", "+00:00"))
        unexpired = expiry.tzinfo is not None and expiry > datetime.now(timezone.utc)
    except (TypeError, ValueError):
        unexpired = False
    if (
        a.get("scope") != "source_access"
        or a.get("status") != "approve"
        or a.get("approval_kind") != "real"
        or not terms.get("processing")
        or not unexpired
        or canonical_url not in terms.get("urls", [])
        or not p["external_allowed"]
        or p["scope"] not in {"source_access", "development_resource"}
        or resource_approval.get("approval_kind") != "real"
        or snapshot["active"].get(p["approval_ref"]["entity_id"]) != p["approval_ref"]["revision"]
    ):
        raise CoreError(
            "FETCH_APPROVAL", "Real unexpired URL-scoped processing and external resource permission required", 4
        )
    # Redirects must fit BOTH policy and exact URLs covered by the approval.
    rules = []
    for approved_url in terms["urls"]:
        _, host, path = checked_url(approved_url, policy["allowed_domains"])
        rules.append({"host": host, "paths": [path]})
    if not spec["ingest"]["rights"]["processing"] or spec["ingest"]["format"] != "html_snapshot":
        raise CoreError("FETCH_FORMAT", "Fetch supports permitted saved-HTML parsing only", 4)
    return policy, rules


def fetch(store, url, spec, expected):
    validate_schema("fetch-spec", spec)
    policy = store.io.json("config/source_policy.json")
    url = checked_url(url, policy["allowed_domains"])[0]
    profile = parser_profile("html_snapshot")
    request = {
        "url": url,
        "spec": spec,
        "parser": profile,
        "policy_sha256": digest(policy),
    }
    # Check policy/approval BEFORE even a cached result, and before DNS.
    with store.io.lock(store.lock_path):
        snapshot, _, _ = store._load()
        if snapshot["case_revision"] != expected:
            raise CoreError("CONFLICT", "Read a fresh revision before fetching", 7)
        _, rules = _authorization(store, snapshot, store.records(snapshot), url, spec)
        fingerprint = digest(
            {"schema_version": 1, "case_id": store.case_id, "command": "fetch:finish", "request": request}
        )
        prior = snapshot["operations"].get(fingerprint)
        if prior:
            source_ref = prior["data"]["source_ref"]
            records = store.records(snapshot)
            source = records[key(source_ref)]
            if (
                snapshot["active"].get(source_ref["entity_id"]) != source_ref["revision"]
                or source["payload"]["status"] != "available"
                or not source["payload"]["rights"]["processing"]
            ):
                raise CoreError(
                    "FETCH_STALE",
                    "Cached fetch source is no longer current/available/permitted; no automatic refresh",
                    3,
                )
            return {
                "case_revision": expected,
                "action_id": prior["action_id"],
                "attempt_id": prior["attempt_id"],
                "data": {**prior["data"], "reused": True},
                "warnings": [],
            }

    def reserve(snapshot):
        batch = RecordBatch(store, snapshot)
        _authorization(store, snapshot, batch.records, url, spec)
        payload = {
            "operation": "reserve",
            "operation_key": digest({"adapter": "pinned-https-v1", "url": checked_url(url, rules)[0]}),
            "permission_ref": spec["permission_ref"],
            "external": True,
            "adapter": "pinned-https-v1",
            "estimated_money": None,
        }
        batch.add("action", payload)
        return batch.finish(store._apply_action(snapshot, payload, batch.records))

    reservation = store._mutate("fetch:reserve", request, expected, reserve, reuse_if=lambda *_: False)
    attempt_id = reservation["data"]["reserved_attempt_id"]
    started = time.monotonic()
    try:
        raw, metadata = download(url, rules, spec["limits"])
        parsed = parse_snapshot(raw, spec["ingest"])

        def finish(snapshot):
            batch = RecordBatch(store, snapshot)
            _authorization(store, snapshot, batch.records, url, spec)
            if digest(store.io.json("config/source_policy.json")) != request["policy_sha256"]:
                raise CoreError("POLICY_CHANGED", "Policy changed during fetch; received bytes not imported", 4)
            data = stage_source(batch, raw, parsed, spec["ingest"], url, metadata)
            payload = {
                "operation": "settle",
                "attempt_id": attempt_id,
                "status": "succeeded",
                "usage": unknown_usage((time.monotonic() - started) * 1000),
            }
            batch.add("action", payload)
            store._apply_action(snapshot, payload, batch.records)
            return batch.finish({**data, "network_attempt_id": attempt_id, "download": metadata})

        return store._mutate("fetch:finish", request, store.status()["case_revision"], finish)
    except CoreError as exc:
        status = "outcome_unknown" if exc.exit_code in {5, 6, 7} else "failed"
        payload = {
            "operation": "settle",
            "attempt_id": attempt_id,
            "status": status,
            "usage": unknown_usage((time.monotonic() - started) * 1000),
            "note": exc.code,
        }
        settled = store.record("action", {"payload": payload}, store.status()["case_revision"])
        exc.saved = settled["case_revision"]
        raise
