import hmac
import os
from html import escape
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .db import Article, Event, SessionLocal, Ticket, init_db, now
from .knowledge import seed

app = FastAPI(title="Orbita support drafts")
security = HTTPBasic()


class WebhookIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    ticket_id: str = Field(min_length=1, max_length=100)
    customer_email: EmailStr
    message: str = Field(min_length=1, max_length=10000)
    reply_url: str = Field(min_length=1, max_length=2000)


def operator(credentials: HTTPBasicCredentials = Depends(security)):
    expected = os.getenv("OPERATOR_PASSWORD", "change-me")
    if not (hmac.compare_digest(credentials.username, "operator") and hmac.compare_digest(credentials.password, expected)):
        raise HTTPException(401, "Invalid operator credentials", headers={"WWW-Authenticate": "Basic"})


@app.on_event("startup")
def startup():
    init_db()
    seed()


@app.get("/health")
def health():
    return {"status": "OK"}


@app.post("/webhooks/helpdesk", status_code=202)
def webhook(body: WebhookIn, x_webhook_secret: str = Header(default="")):
    if not hmac.compare_digest(x_webhook_secret, os.getenv("WEBHOOK_SECRET", "local-webhook-secret")):
        raise HTTPException(401, "Invalid webhook secret")
    parsed = urlsplit(body.reply_url)
    allowed = urlsplit(os.getenv("HELPDESK_ALLOWED_ORIGIN", "http://mock-helpdesk:8001"))
    if (parsed.scheme, parsed.hostname, parsed.port) != (allowed.scheme, allowed.hostname, allowed.port) or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != f"/tickets/{body.ticket_id}/replies":
        raise HTTPException(422, "reply_url must target the configured helpdesk origin and ticket")
    with SessionLocal.begin() as db:
        inserted = db.execute(insert(Event).values(event_id=body.event_id, ticket_id=body.ticket_id).on_conflict_do_nothing(index_elements=["event_id"]).returning(Event.event_id)).scalar_one_or_none()
        if inserted:
            db.execute(insert(Ticket).values(ticket_id=body.ticket_id, customer_email=str(body.customer_email), message=body.message, reply_url=body.reply_url, status="queued").on_conflict_do_nothing(index_elements=["ticket_id"]))
        else:
            prior = db.get(Event, body.event_id)
            if prior.ticket_id != body.ticket_id:
                raise HTTPException(409, "event_id already belongs to another ticket")
    return {"accepted": True, "event_id": body.event_id}


@app.get("/kb/{slug}", response_class=HTMLResponse)
def article(slug: str):
    with SessionLocal() as db:
        item = db.scalar(select(Article).where(Article.slug == slug))
        if not item:
            raise HTTPException(404)
        return f"<h1>{escape(item.title)}</h1><p>{escape(item.body)}</p>"


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(operator)])
def dashboard():
    with SessionLocal() as db:
        tickets = db.scalars(select(Ticket).order_by(Ticket.id.desc()).limit(200)).all()
        parts = ["<html><head><meta charset='utf-8'><title>Orbita support</title></head><body><h1>Звернення Orbita</h1><p>Оновіть сторінку для нових чернеток.</p>"]
        for ticket in tickets:
            parts.append(f"<article style='border:1px solid #ccc;padding:12px;margin:12px 0'><h2>{escape(ticket.ticket_id)} — {escape(ticket.status)}</h2><p>{escape(ticket.customer_email)}: {escape(ticket.message)}</p>")
            if ticket.draft:
                parts.append(f"<pre style='white-space:pre-wrap'>{escape(ticket.draft)}</pre>")
            if ticket.error:
                parts.append(f"<p>Помилка: {escape(ticket.error)}</p>")
            if ticket.status == "draft":
                parts.append(f"<form method='post' action='/tickets/{ticket.id}/approve'><textarea name='draft' rows='6' cols='90'>{escape(ticket.draft or '')}</textarea><br><button>Підтвердити й надіслати</button></form><form method='post' action='/tickets/{ticket.id}/reject'><button>Відхилити</button></form>")
            parts.append("</article>")
        return "".join(parts) + "</body></html>"


@app.post("/tickets/{ticket_pk}/approve", dependencies=[Depends(operator)])
def approve(ticket_pk: int, draft: str = Form(...)):
    if not draft.strip() or len(draft) > 20000:
        raise HTTPException(422, "Invalid draft")
    with SessionLocal.begin() as db:
        ticket = db.get(Ticket, ticket_pk, with_for_update=True)
        if not ticket:
            raise HTTPException(404)
        if ticket.status != "draft":
            raise HTTPException(409, "Ticket is not awaiting review")
        ticket.draft = draft.strip()
        ticket.status = "approved"
        ticket.next_attempt_at = now()
        ticket.attempts = 0
    return RedirectResponse("/", status_code=303)


@app.post("/tickets/{ticket_pk}/reject", dependencies=[Depends(operator)])
def reject(ticket_pk: int):
    with SessionLocal.begin() as db:
        ticket = db.get(Ticket, ticket_pk, with_for_update=True)
        if not ticket:
            raise HTTPException(404)
        if ticket.status != "draft":
            raise HTTPException(409, "Ticket is not awaiting review")
        ticket.status = "rejected"
    return RedirectResponse("/", status_code=303)
