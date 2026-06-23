from __future__ import annotations

import httpx

# QStash is multi-region with per-region endpoints and tokens. The global default
# routes to EU; US accounts must use https://qstash-us-east-1.upstash.io. Set the
# QSTASH_URL env var to match where your QStash credentials were created.
DEFAULT_QSTASH_URL = "https://qstash.upstash.io"


def publish_job(
    token: str,
    destination_url: str,
    job: dict,
    *,
    base_url: str = DEFAULT_QSTASH_URL,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
) -> None:
    """Enqueue a job with QStash for delivery to ``destination_url``.

    QStash accepts the message synchronously (fast — keeps us under Slack's 3s
    deadline) and then POSTs ``job`` to the worker endpoint, retrying on failure.
    """
    client = client or httpx.Client(timeout=timeout)
    response = client.post(
        base_url.rstrip("/") + "/v2/publish/" + destination_url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=job,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"QStash publish failed: HTTP {response.status_code}: {response.text}")


def verify_qstash_signature(
    current_signing_key: str,
    next_signing_key: str,
    signature: str,
    body: str,
    url: str | None = None,
) -> bool:
    """Verify a QStash-delivered request via the official SDK's JWT receiver."""
    from qstash import Receiver

    receiver = Receiver(
        current_signing_key=current_signing_key,
        next_signing_key=next_signing_key,
    )
    try:
        receiver.verify(signature=signature, body=body, url=url)
        return True
    except Exception:
        return False
