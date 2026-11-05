import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, func, or_, select, text

from .db import LlmCall, SessionLocal, Ticket, init_db, now
from .knowledge import find_relevant, seed
from .llm import generate

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
LEASE_SECONDS = 120


def claim():
    current = now()
    with SessionLocal.begin() as db:
        ticket = db.scalar(
            select(Ticket).where(
                Ticket.status.in_(["queued", "generating", "approved", "sending"]),
                Ticket.next_attempt_at <= current,
                or_(Ticket.lease_until.is_(None), Ticket.lease_until < current),
            ).order_by(Ticket.next_attempt_at, Ticket.id).with_for_update(skip_locked=True).limit(1)
        )
        if not ticket:
            return None
        stage = "generate" if ticket.status in ("queued", "generating") else "send"
        ticket.status = "generating" if stage == "generate" else "sending"
        ticket.lease_until = current + timedelta(seconds=LEASE_SECONDS)
        ticket.lease_token = str(uuid.uuid4())
        ticket.attempts += 1
        return ticket.id, ticket.lease_token, stage, ticket.message, ticket.reply_url, ticket.ticket_id, ticket.draft


def reserve_llm_slot():
    with SessionLocal.begin() as db:
        # One transaction-wide advisory lock serializes reservations across workers.
        db.execute(text("SELECT pg_advisory_xact_lock(7142026)"))
        cutoff = now() - timedelta(minutes=1)
        db.execute(delete(LlmCall).where(LlmCall.started_at < cutoff))
        count = db.scalar(select(func.count()).select_from(LlmCall))
        if count >= 60:
            return False
        db.add(LlmCall(started_at=now()))
        return True


def complete(ticket_pk, token, stage, draft=None, article_ids=None):
    with SessionLocal.begin() as db:
        ticket = db.get(Ticket, ticket_pk, with_for_update=True)
        if not ticket or ticket.lease_token != token:
            return
        ticket.status = "draft" if stage == "generate" else "sent"
        if stage == "generate":
            ticket.draft = draft
            ticket.article_ids = article_ids
        ticket.error = None
        ticket.lease_token = None
        ticket.lease_until = None


def retry(ticket_pk, token, stage, error, delay=None):
    with SessionLocal.begin() as db:
        ticket = db.get(Ticket, ticket_pk, with_for_update=True)
        if not ticket or ticket.lease_token != token:
            return
        ticket.status = "queued" if stage == "generate" else "approved"
        ticket.error = str(error)[:1000]
        ticket.next_attempt_at = now() + timedelta(seconds=delay if delay is not None else min(300, 2 ** min(ticket.attempts, 8)))
        ticket.lease_until = None
        ticket.lease_token = None


def valid_reply_url(url, ticket_id):
    try:
        parsed = urlsplit(url)
        allowed = urlsplit(os.getenv("HELPDESK_ALLOWED_ORIGIN", "http://mock-helpdesk:8001"))
        return ((parsed.scheme, parsed.hostname, parsed.port) == (allowed.scheme, allowed.hostname, allowed.port)
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path == f"/tickets/{ticket_id}/replies")
    except ValueError:
        return False


def process(job):
    ticket_pk, token, stage, message, reply_url, ticket_id, draft = job
    try:
        if stage == "generate":
            if not reserve_llm_slot():
                retry(ticket_pk, token, stage, "LLM rate limit", 2)
                return
            articles = find_relevant(message)
            answer = generate(message, articles)
            complete(ticket_pk, token, stage, answer, ",".join(str(item[1]) for item in articles))
        else:
            if not valid_reply_url(reply_url, ticket_id):
                raise ValueError("Reply URL origin is not allowed")
            response = httpx.post(reply_url, json={"ticket_id": ticket_id, "message": draft}, headers={"Idempotency-Key": f"reply:{ticket_id}"}, timeout=5)
            if response.status_code != 201:
                raise RuntimeError(f"Helpdesk returned {response.status_code}: {response.text[:200]}")
            complete(ticket_pk, token, stage)
    except Exception as exc:
        log.exception("Ticket %s %s failed", ticket_id, stage)
        retry(ticket_pk, token, stage, exc)


def main():
    init_db()
    seed()
    concurrency = int(os.getenv("WORKER_CONCURRENCY", "32"))
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        active = set()
        while True:
            active = {f for f in active if not f.done()}
            while len(active) < concurrency:
                job = claim()
                if not job:
                    break
                active.add(pool.submit(process, job))
            time.sleep(0.25 if active else 1)


if __name__ == "__main__":
    main()
