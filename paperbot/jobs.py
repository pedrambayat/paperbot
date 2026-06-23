from __future__ import annotations

import httpx

QSTASH_PUBLISH_URL = "https://qstash.upstash.io/v2/publish/"


def publish_job(
    token: str,
    destination_url: str,
    job: dict,
    *,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
) -> None:
    """Enqueue a job with QStash for delivery to ``destination_url``.

    QStash accepts the message synchronously (fast — keeps us under Slack's 3s
    deadline) and then POSTs ``job`` to the worker endpoint, retrying on failure.
    """
    client = client or httpx.Client(timeout=timeout)
    response = client.post(
        QSTASH_PUBLISH_URL + destination_url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=job,
    )
    response.raise_for_status()


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
