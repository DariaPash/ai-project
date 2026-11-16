"""Production bounded download worker; no environment proxy or injectable backend."""

import base64
import socket
import ssl
import sys

from .errors import CoreError
from .safeio import canonical, parse_json


def main():
    try:
        from .safe_fetch import _download

        request = parse_json(sys.stdin.buffer.read(65536))
        raw, metadata = _download(request["url"], request["rules"], request["limits"])
        receipt = {"ok": True, "raw_base64": base64.b64encode(raw).decode("ascii"), "metadata": metadata}
    except CoreError as exc:
        receipt = {"ok": False, "code": exc.code, "reason": exc.reason, "exit": exc.exit_code}
    except ssl.SSLCertVerificationError:
        receipt = {
            "ok": False,
            "code": "TLS_CERTIFICATE",
            "reason": "TLS certificate/hostname verification failed",
            "exit": 4,
        }
    except (OSError, socket.timeout):
        receipt = {
            "ok": False,
            "code": "FETCH_IO",
            "reason": "Network/DNS/TLS operation failed; no automatic retry",
            "exit": 5,
        }
    except Exception:
        receipt = {"ok": False, "code": "FETCH_RESPONSE", "reason": "Malformed or incomplete HTTP response", "exit": 5}
    sys.stdout.buffer.write(canonical(receipt))


if __name__ == "__main__":
    main()
