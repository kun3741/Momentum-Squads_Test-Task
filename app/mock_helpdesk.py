import os
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .db import MockReply, MockScenario, SessionLocal, init_db

app = FastAPI(title="Mock helpdesk")


class ReplyIn(BaseModel):
    ticket_id: str
    message: str


class ScenarioIn(BaseModel):
    mode: str


@app.on_event("startup")
def startup():
    init_db()


@app.post("/tickets/{ticket_id}/replies", status_code=201)
def create_reply(ticket_id: str, body: ReplyIn, idempotency_key: str = Header(alias="Idempotency-Key")):
    if body.ticket_id != ticket_id:
        raise HTTPException(400, "Ticket mismatch")
    with SessionLocal.begin() as db:
        scenario = db.get(MockScenario, ticket_id)
        if scenario and scenario.mode == "500":
            raise HTTPException(503, "Injected failure")
        stmt = insert(MockReply).values(ticket_id=ticket_id, idempotency_key=idempotency_key, message=body.message).on_conflict_do_nothing(index_elements=["ticket_id", "idempotency_key"])
        db.execute(stmt)
        prior = db.scalar(select(MockReply).where(MockReply.ticket_id == ticket_id, MockReply.idempotency_key == idempotency_key))
        if prior.message != body.message:
            raise HTTPException(409, "Idempotency key used with different message")
        if scenario and scenario.mode == "timeout-after-write":
            time.sleep(12)
    return {"id": prior.id, "duplicate": False}


@app.put("/scenarios/{ticket_id}")
def set_scenario(ticket_id: str, body: ScenarioIn, x_mock_admin_secret: str = Header(default="")):
    if x_mock_admin_secret != os.getenv("WEBHOOK_SECRET", "local-webhook-secret"):
        raise HTTPException(401)
    if body.mode not in ("normal", "500", "timeout-after-write"):
        raise HTTPException(422)
    with SessionLocal.begin() as db:
        db.execute(insert(MockScenario).values(ticket_id=ticket_id, mode=body.mode).on_conflict_do_update(index_elements=["ticket_id"], set_={"mode": body.mode}))
    return {"mode": body.mode}


@app.get("/replies")
def list_replies(x_mock_admin_secret: str = Header(default="")):
    if x_mock_admin_secret != os.getenv("WEBHOOK_SECRET", "local-webhook-secret"):
        raise HTTPException(401)
    with SessionLocal() as db:
        return [{"ticket_id": r.ticket_id, "message": r.message} for r in db.scalars(select(MockReply).order_by(MockReply.id)).all()]
