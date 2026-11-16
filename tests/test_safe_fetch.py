import copy
import socket
import ssl

import pytest

from tools.errors import CoreError
from tools.safe_fetch import _download, _request, checked_url, fetch, public_addresses
from .helpers import init
from .step02_helpers import source_spec
from tools.store import Store

RULES = [{"host": "example.org", "paths": ["/", "/next"]}]
LIMITS = {
    "max_bytes": 1000,
    "timeout_ms": 3000,
    "connect_timeout_ms": 1000,
    "max_hops": 2,
    "allowed_mime": ["text/html"],
}


def identity(host, ip):
    return {
        "peer_ip": ip,
        "tls_sni": host,
        "http_host": host,
        "certificate_verified": True,
        "certificate_sha256": "a" * 64,
        "tls_version": "TEST DOUBLE, NOT LIVE TLS",
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/",
        "https://example.org:444/",
        "https://user:pass@example.org/",
        "https://example.org/other",
        "https://unlisted.example/",
        "https://example.org/%2e%2e/",
        "https://example.org/../",
        "https://example.org./",
        "https://example.org/?token=hidden",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://example.org/\\x",
        "https://example.org/#fragment",
    ],
)
def test_unsafe_urls_never_resolve_or_connect(url):
    with pytest.raises(CoreError) as error:
        _download(
            url,
            RULES,
            LIMITS,
            _resolver=lambda *_: pytest.fail("unsafe URL resolved"),
            _transport=lambda *_: pytest.fail("unsafe URL connected"),
        )
    assert error.value.exit_code == 4


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.1.2.3"],
        ["169.254.169.254"],
        ["0.0.0.0"],
        ["224.0.0.1"],
        ["::1"],
        ["fc00::1"],
        ["fe80::1"],
        ["::ffff:127.0.0.1"],
        ["93.184.216.34", "192.168.1.1"],
        ["2606:4700:4700::1111", "::1"],
    ],
)
def test_all_dns_answers_global_private_connect_count_zero(addresses):
    calls = []
    with pytest.raises(CoreError) as error:
        _download(
            "https://example.org/",
            RULES,
            LIMITS,
            _resolver=lambda _: addresses,
            _transport=lambda *args: calls.append(args),
        )
    assert error.value.exit_code == 4 and calls == []


def test_rebinding_uses_one_resolution_and_numeric_pin(monkeypatch):
    dns = []
    connections = []

    def resolve(host):
        dns.append(host)
        return ["93.184.216.34"] if len(dns) == 1 else ["127.0.0.1"]

    def request(host, path, ip, limits, deadline):
        connections.append((host, path, ip))
        return 200, {"content-type": "text/html"}, b"<p>known quote</p>", identity(host, ip)

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    raw, meta = _download("https://example.org/", RULES, LIMITS, _resolver=resolve, _transport=request)
    assert raw == b"<p>known quote</p>" and len(dns) == 1
    assert connections == [("example.org", "/", "93.184.216.34")]
    assert meta["redirect_chain"][0]["certificate_verified"]


def test_redirect_revalidates_dns_private_target_never_connected():
    connected = []
    resolved = []

    def resolver(host):
        resolved.append(host)
        return ["93.184.216.34"] if len(resolved) == 1 else ["127.0.0.1"]

    def transport(host, path, ip, *_):
        connected.append(ip)
        return 302, {"location": "/next"}, b"", identity(host, ip)

    with pytest.raises(CoreError) as error:
        _download("https://example.org/", RULES, LIMITS, _resolver=resolver, _transport=transport)
    assert error.value.code == "DNS_PRIVATE" and connected == ["93.184.216.34"]


@pytest.mark.parametrize("target", ["https://127.0.0.1/", "http://example.org/", "https://unlisted.example/", "/"])
def test_redirect_scope_and_cycles(target):
    calls = []

    def transport(host, path, ip, *_):
        calls.append(ip)
        return 302, {"location": target}, b"", identity(host, ip)

    with pytest.raises(CoreError) as error:
        _download("https://example.org/", RULES, LIMITS, _resolver=lambda _: ["93.184.216.34"], _transport=transport)
    assert error.value.exit_code == 4 and len(calls) == 1


@pytest.mark.parametrize("defect", ["peer", "tls", "sni", "host", "mime", "encoding", "oversize", "status"])
def test_response_identity_mime_encoding_and_limits(defect):
    def transport(host, path, ip, *_):
        meta = identity(host, ip)
        headers = {"content-type": "text/html"}
        raw = b"<p>x</p>"
        status = 200
        if defect == "peer":
            meta["peer_ip"] = "127.0.0.1"
        if defect == "tls":
            meta["certificate_verified"] = False
        if defect == "sni":
            meta["tls_sni"] = "wrong.example"
        if defect == "host":
            meta["http_host"] = "wrong.example"
        if defect == "mime":
            headers["content-type"] = "application/octet-stream"
        if defect == "encoding":
            headers["content-encoding"] = "gzip"
        if defect == "oversize":
            raw = b"x" * 1001
        if defect == "status":
            status = 403
        return status, headers, raw, meta

    with pytest.raises(CoreError) as error:
        _download("https://example.org/", RULES, LIMITS, _resolver=lambda _: ["93.184.216.34"], _transport=transport)
    assert error.value.exit_code == (3 if defect == "status" else 4)


def test_production_transport_numeric_socket_sni_host_verified_context_and_stream_cap(monkeypatch):
    import time
    import tools.safe_fetch as module

    connections = []
    sent = []
    sni = []
    contexts = []

    class FakeSocket:
        def settimeout(self, value):
            assert value > 0

        def connect(self, address):
            connections.append(address)

        def getpeername(self):
            return ("93.184.216.34", 443)

        def sendall(self, raw):
            sent.append(raw)

        def getpeercert(self, binary_form):
            return b"fake-cert-not-live"

        def version(self):
            return "TEST ONLY"

        def close(self):
            pass

    class FakeContext:
        def wrap_socket(self, raw, server_hostname):
            sni.append(server_hostname)
            return raw

    real_context = ssl.create_default_context

    def context():
        real = real_context()
        contexts.append((real.check_hostname, real.verify_mode))
        return FakeContext()

    class Headers:
        def get_all(self, name, default):
            return ["text/html"] if name == "Content-Type" else []

    class FakeResponse:
        status = 200
        headers = Headers()

        def __init__(self, *_):
            self.count = 0

        def begin(self):
            pass

        def read1(self, size):
            self.count += 1
            return b"x" * size

    monkeypatch.setattr(socket, "socket", lambda *_: FakeSocket())
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: pytest.fail("second implicit DNS"))
    monkeypatch.setattr(module.ssl, "create_default_context", context)
    monkeypatch.setattr(module.http.client, "HTTPResponse", FakeResponse)
    with pytest.raises(CoreError) as error:
        _request("example.org", "/", "93.184.216.34", LIMITS, time.monotonic() + 3)
    assert error.value.code == "FETCH_BYTES"
    assert connections == [("93.184.216.34", 443)] and sni == ["example.org"]
    assert contexts == [(True, ssl.CERT_REQUIRED)]
    assert b"Host: example.org\r\n" in sent[0] and b"Accept-Encoding: identity\r\n" in sent[0]
    assert b"Authorization" not in sent[0] and b"Cookie" not in sent[0]


def test_public_ipv6_and_mapped_ipv4_normalization():
    assert public_addresses(["::ffff:93.184.216.34"]) == ["93.184.216.34"]
    assert public_addresses(["2606:4700:4700::1111"]) == ["2606:4700:4700::1111"]


@pytest.mark.parametrize("address", ["64:ff9b::7f00:1", "2002:7f00:1::1", "2001:0:4136:e378:8000:63bf:3fff:fdd2"])
def test_transition_ipv6_not_a_private_target_escape(address):
    with pytest.raises(CoreError) as error:
        public_addresses([address])
    assert error.value.exit_code == 4


def test_real_fetch_denied_without_policy_or_permission_before_dns(project, monkeypatch):
    init(project)
    import tools.safe_fetch as module

    monkeypatch.setattr(module, "download", lambda *_: pytest.fail("unauthorized egress"))
    _, ingest_spec = source_spec("html")
    spec = {
        "schema_version": 1,
        "source_access_approval_ref": {"case_id": "test-core", "entity_id": "APR-001", "revision": 1},
        "permission_ref": {"case_id": "test-core", "entity_id": "PER-001", "revision": 1},
        "ingest": ingest_spec,
        "limits": LIMITS,
    }
    with Store(project, "test-core") as store:
        with pytest.raises(CoreError) as error:
            fetch(store, "https://example.org/", spec, 0)
        assert error.value.code == "DOMAIN_DENIED"
        assert store.status()["data"]["attempts"] == {}


def test_fixture_approval_cannot_authorize_network_even_with_test_policy(project, monkeypatch):
    import json
    from .helpers import approval, permission
    import tools.safe_fetch as module

    init(project)
    policy_path = project / "config/source_policy.json"
    policy = json.loads(policy_path.read_text())
    policy["allowed_domains"] = RULES
    policy_path.write_text(json.dumps(policy))
    apr = approval(
        project,
        "source_access",
        terms={"urls": ["https://example.org/"], "processing": True, "expires_at": "2099-01-01T00:00:00Z"},
    )
    per = permission(project)
    monkeypatch.setattr(module, "download", lambda *_: pytest.fail("fixture permission performed egress"))
    _, ingest_spec = source_spec("html")
    spec = {
        "schema_version": 1,
        "source_access_approval_ref": apr,
        "permission_ref": per,
        "ingest": ingest_spec,
        "limits": LIMITS,
    }
    with Store(project, "test-core") as store:
        with pytest.raises(CoreError) as error:
            fetch(store, "https://example.org/", spec, store.status()["case_revision"])
        assert error.value.code == "FETCH_APPROVAL" and store.status()["data"]["attempts"] == {}


def test_successful_redirect_preserves_bytes_hash_and_each_tls_identity():
    from tools.contracts import sha

    def transport(host, path, ip, *_):
        if path == "/":
            return 302, {"location": "/next"}, b"", identity(host, ip)
        return 200, {"content-type": "text/html; charset=utf-8"}, b"<p>saved quote</p>", identity(host, ip)

    raw, metadata = _download(
        "https://example.org/", RULES, LIMITS, _resolver=lambda _: ["93.184.216.34"], _transport=transport
    )
    assert metadata["sha256"] == sha(raw) and metadata["final_url"] == "https://example.org/next"
    assert len(metadata["redirect_chain"]) == 2
    assert all(h["tls_sni"] == h["http_host"] == "example.org" for h in metadata["redirect_chain"])


def test_worker_deadline_is_single_attempt_and_does_not_inherit_proxy(monkeypatch):
    import subprocess
    import tools.safe_fetch as module

    killed = []
    calls = []

    class Process:
        def communicate(self, *args, **kwargs):
            if kwargs.get("timeout"):
                raise subprocess.TimeoutExpired("test-fetch", 1)
            return b"", b""

        def kill(self):
            killed.append(True)

    def launch(*args, **kwargs):
        calls.append(args)
        assert not any("PROXY" in key.upper() for key in kwargs["env"])
        return Process()

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    with pytest.raises(CoreError) as error:
        module.download("https://example.org/", RULES, LIMITS)
    assert error.value.code == "FETCH_TIMEOUT" and len(calls) == len(killed) == 1


def test_certificate_mismatch_fails_closed_in_numeric_transport(monkeypatch):
    import time
    import tools.safe_fetch as module

    calls = []

    class Socket:
        def settimeout(self, *_):
            pass

        def connect(self, peer):
            calls.append(peer)

        def close(self):
            pass

    class Context:
        def wrap_socket(self, *args, **kwargs):
            raise ssl.SSLCertVerificationError("TEST certificate mismatch")

    monkeypatch.setattr(socket, "socket", lambda *_: Socket())
    monkeypatch.setattr(module.ssl, "create_default_context", lambda: Context())
    with pytest.raises(ssl.SSLCertVerificationError):
        _request("example.org", "/", "93.184.216.34", LIMITS, time.monotonic() + 3)
    assert calls == [("93.184.216.34", 443)]
