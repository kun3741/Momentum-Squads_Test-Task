"""Submit 500 synthetic webhooks and verify every ticket is persisted."""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from integration import AUTH, BASE, REPLY_ORIGIN, SECRET, request


def main():
    if os.getenv("LOAD_TEST_ALLOWED") != "1":
        raise SystemExit("Set LOAD_TEST_ALLOWED=1 only against a disposable test service")
    suffix = uuid.uuid4().hex[:8]
    ids = [f"T-load-{suffix}-{number}" for number in range(500)]

    def deliver(ticket_id):
        payload = {
            "event_id": "evt-" + ticket_id,
            "ticket_id": ticket_id,
            "customer_email": "load@example.com",
            "message": "PDF export failed",
            "reply_url": f"{REPLY_ORIGIN}/tickets/{ticket_id}/replies",
        }
        for attempt in range(5):
            started = time.monotonic()
            code, body = request("POST", BASE + "/webhooks/helpdesk", payload, {"X-Webhook-Secret": SECRET})
            elapsed = time.monotonic() - started
            assert elapsed < 2, f"Webhook {ticket_id} took {elapsed:.2f}s"
            if code == 202:
                return elapsed, attempt
            if code != 503:
                raise AssertionError(f"Webhook {ticket_id} returned {code}: {body}")
            time.sleep(0.1 * (attempt + 1))
        raise AssertionError(f"Webhook {ticket_id} was not accepted after retries")

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(deliver, ids))

    def verify(ticket_id):
        code, body = request("GET", f"{BASE}/api/tickets/{ticket_id}", headers={"Authorization": AUTH})
        assert code == 200 and body["ticket_id"] == ticket_id, (ticket_id, code, body)

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(verify, ids))

    print(f"PASS: 500 unique tickets persisted; slowest acknowledgement {max(t for t, _ in results):.3f}s; retries {sum(n for _, n in results)}")


if __name__ == "__main__":
    main()
