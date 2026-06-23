from __future__ import annotations

import hashlib
import hmac
import time

# Slack rejects requests whose timestamp is more than 5 minutes off, to limit replay.
MAX_AGE_SECONDS = 60 * 5


def verify_slack_signature(
    signing_secret: str,
    timestamp: str,
    signature: str,
    body: bytes,
    *,
    now: float | None = None,
    max_age: int = MAX_AGE_SECONDS,
) -> bool:
    """Verify an incoming Slack request signature.

    Slack signs each request as ``v0=HMAC_SHA256(secret, "v0:{timestamp}:{body}")``
    and sends it in the ``X-Slack-Signature`` header alongside
    ``X-Slack-Request-Timestamp``. We recompute the HMAC and compare in constant
    time, and reject stale timestamps to limit replay.
    """
    try:
        request_ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    current = time.time() if now is None else now
    if abs(current - request_ts) > max_age:
        return False

    basestring = b"v0:" + str(timestamp).encode("utf-8") + b":" + body
    digest = hmac.new(signing_secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    expected = "v0=" + digest
    return hmac.compare_digest(expected, signature)
