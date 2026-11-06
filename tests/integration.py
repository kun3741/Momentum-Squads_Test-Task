"""Run against the Compose stack: python tests/integration.py."""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def setting(name, default):
    if name in os.environ:
        return os.environ[name]
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.partition("=")[2].strip().strip('"')
    return default


BASE = setting("BASE_URL", "http://localhost:8000")
MOCK = setting("MOCK_BASE_URL", "http://localhost:8001")
REPLY_ORIGIN = setting("HELPDESK_ALLOWED_ORIGIN", "http://mock-helpdesk:8001")
PASSWORD = setting("OPERATOR_PASSWORD", "change-me")
SECRET = setting("WEBHOOK_SECRET", "local-webhook-secret")
AUTH = "Basic " + base64.b64encode(f"operator:{PASSWORD}".encode()).decode()


def request(method, url, body=None, headers=None, timeout=10, form=False):
    data = None
    sent_headers = dict(headers or {})
    if isinstance(body, dict) and not form:
        data = json.dumps(body).encode()
        sent_headers["Content-Type"] = "application/json"
    elif body is not None:
        data = urllib.parse.urlencode(body).encode()
        sent_headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, method=method, headers=sent_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw.startswith(("{", "[")) else raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def wait_for(ticket_id, status, timeout=100, require_error=False):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        code, last = request("GET", f"{BASE}/api/tickets/{ticket_id}", headers={"Authorization": AUTH})
        if code == 200 and last["status"] == status and (not require_error or last["error"]):
            return last
        time.sleep(0.5)
    raise AssertionError(f"{ticket_id} did not reach {status}; last state: {last}")


def set_scenario(ticket_id, mode):
    code, body = request("PUT", f"{MOCK}/scenarios/{ticket_id}", {"mode": mode}, {"X-Mock-Admin-Secret": SECRET})
    assert code == 200, body


def replies(ticket_id):
    code, body = request("GET", f"{MOCK}/replies", headers={"X-Mock-Admin-Secret": SECRET})
    assert code == 200, body
    return [item for item in body if item["ticket_id"] == ticket_id]


def approve(ticket):
    token = hmac.new(PASSWORD.encode(), f"{ticket['id']}:approve".encode(), hashlib.sha256).hexdigest()
    code, body = request("POST", f"{BASE}/tickets/{ticket['id']}/approve", {"draft": ticket["draft"], "review_token": token}, {"Authorization": AUTH}, form=True)
    assert code == 200, body  # urllib follows the 303 redirect to the dashboard.


def reject(ticket):
    token = hmac.new(PASSWORD.encode(), f"{ticket['id']}:reject".encode(), hashlib.sha256).hexdigest()
    code, body = request("POST", f"{BASE}/tickets/{ticket['id']}/reject", {"review_token": token}, {"Authorization": AUTH}, form=True)
    assert code == 200, body


def retry_failed(ticket):
    token = hmac.new(PASSWORD.encode(), f"{ticket['id']}:retry".encode(), hashlib.sha256).hexdigest()
    code, body = request("POST", f"{BASE}/tickets/{ticket['id']}/retry", {"review_token": token}, {"Authorization": AUTH}, form=True)
    assert code == 200, body


def main():
    code, body = request("GET", BASE + "/health")
    assert (code, body) == (200, "OK")
    suffix = uuid.uuid4().hex[:8]
    ticket_id = "T-integration-" + suffix
    event_id = "evt-integration-" + suffix
    payload = {
        "event_id": event_id,
        "ticket_id": ticket_id,
        "customer_email": "customer@example.com",
        "message": "Не можу експортувати звіт у PDF",
        "reply_url": f"{REPLY_ORIGIN}/tickets/{ticket_id}/replies",
    }

    def deliver(_):
        started = time.monotonic()
        result = request("POST", BASE + "/webhooks/helpdesk", payload, {"X-Webhook-Secret": SECRET})
        return result[0], time.monotonic() - started

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(deliver, range(12)))
    assert all(code == 202 for code, _ in results), results
    assert max(elapsed for _, elapsed in results) < 2, results
    draft = wait_for(ticket_id, "draft")
    assert "/kb/pdf-export" in draft["draft"], draft
    assert replies(ticket_id) == []
    approve(draft)
    wait_for(ticket_id, "sent")
    assert len(replies(ticket_id)) == 1
    print("PASS: concurrent duplicate webhooks, fast acknowledgement, review and one reply")

    timeout_ticket = "T-timeout-" + suffix
    set_scenario(timeout_ticket, "timeout-after-write")
    timeout_payload = dict(payload, event_id="evt-timeout-" + suffix, ticket_id=timeout_ticket,
                           reply_url=f"{REPLY_ORIGIN}/tickets/{timeout_ticket}/replies")
    code, body = request("POST", BASE + "/webhooks/helpdesk", timeout_payload, {"X-Webhook-Secret": SECRET})
    assert code == 202, body
    approve(wait_for(timeout_ticket, "draft"))
    wait_for(timeout_ticket, "approved", timeout=30, require_error=True)  # First send timed out after the mock saved the reply.
    assert len(replies(timeout_ticket)) == 1
    set_scenario(timeout_ticket, "normal")
    wait_for(timeout_ticket, "sent", timeout=60)
    assert len(replies(timeout_ticket)) == 1
    print("PASS: timeout after write retries safely with the same idempotency key")

    failing_ticket = "T-5xx-" + suffix
    set_scenario(failing_ticket, "500")
    failing_payload = dict(payload, event_id="evt-5xx-" + suffix, ticket_id=failing_ticket,
                           reply_url=f"{REPLY_ORIGIN}/tickets/{failing_ticket}/replies")
    code, body = request("POST", BASE + "/webhooks/helpdesk", failing_payload, {"X-Webhook-Secret": SECRET})
    assert code == 202, body
    approve(wait_for(failing_ticket, "draft"))
    wait_for(failing_ticket, "approved", timeout=30, require_error=True)
    assert replies(failing_ticket) == []
    set_scenario(failing_ticket, "normal")
    wait_for(failing_ticket, "sent", timeout=60)
    assert len(replies(failing_ticket)) == 1
    print("PASS: 5xx is retried after the mock recovers")

    permanent_ticket = "T-4xx-" + suffix
    set_scenario(permanent_ticket, "400")
    permanent_payload = dict(payload, event_id="evt-4xx-" + suffix, ticket_id=permanent_ticket,
                             reply_url=f"{REPLY_ORIGIN}/tickets/{permanent_ticket}/replies")
    code, body = request("POST", BASE + "/webhooks/helpdesk", permanent_payload, {"X-Webhook-Secret": SECRET})
    assert code == 202, body
    approve(wait_for(permanent_ticket, "draft"))
    failed = wait_for(permanent_ticket, "send_failed", timeout=30, require_error=True)
    assert replies(permanent_ticket) == []
    set_scenario(permanent_ticket, "normal")
    retry_failed(failed)
    wait_for(permanent_ticket, "sent", timeout=30)
    assert len(replies(permanent_ticket)) == 1
    print("PASS: permanent 4xx stops automatic retries and operator can resume sending")

    rejected_ticket = "T-rejected-" + suffix
    rejected_payload = dict(payload, event_id="evt-rejected-" + suffix, ticket_id=rejected_ticket,
                            reply_url=f"{REPLY_ORIGIN}/tickets/{rejected_ticket}/replies")
    code, body = request("POST", BASE + "/webhooks/helpdesk", rejected_payload, {"X-Webhook-Secret": SECRET})
    assert code == 202, body
    reject(wait_for(rejected_ticket, "draft"))
    wait_for(rejected_ticket, "rejected")
    assert replies(rejected_ticket) == []
    print("PASS: rejected draft is never sent")


if __name__ == "__main__":
    main()
