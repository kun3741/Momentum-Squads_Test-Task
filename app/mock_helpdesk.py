import os
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .db import MockReply, MockScenario, SessionLocal

app = FastAPI(title="Mock helpdesk")


class ReplyIn(BaseModel):
    ticket_id: str
    message: str


class ScenarioIn(BaseModel):
    mode: str


@app.post("/tickets/{ticket_id}/replies", status_code=201)
def create_reply(ticket_id: str, body: ReplyIn, idempotency_key: str = Header(alias="Idempotency-Key")):
    if body.ticket_id != ticket_id:
        raise HTTPException(400, "Ticket mismatch")
    with SessionLocal.begin() as db:
        scenario = db.get(MockScenario, ticket_id)
        if scenario and scenario.mode == "400":
            raise HTTPException(400, "Injected permanent failure")
        if scenario and scenario.mode == "500":
            raise HTTPException(503, "Injected failure")
        stmt = insert(MockReply).values(ticket_id=ticket_id, idempotency_key=idempotency_key, message=body.message).on_conflict_do_nothing(index_elements=["ticket_id", "idempotency_key"])
        inserted = db.execute(stmt.returning(MockReply.id)).scalar_one_or_none()
        prior = db.scalar(select(MockReply).where(MockReply.ticket_id == ticket_id, MockReply.idempotency_key == idempotency_key))
        if prior.message != body.message:
            raise HTTPException(409, "Idempotency key used with different message")
        timeout_after_write = bool(scenario and scenario.mode == "timeout-after-write")
        duplicate = inserted is None
        reply_id = prior.id
    if timeout_after_write:
        time.sleep(12)
    return {"id": reply_id, "duplicate": duplicate}


@app.put("/scenarios/{ticket_id}")
def set_scenario(ticket_id: str, body: ScenarioIn, x_mock_admin_secret: str = Header(default="")):
    if x_mock_admin_secret != os.getenv("WEBHOOK_SECRET", "local-webhook-secret"):
        raise HTTPException(401)
    if body.mode not in ("normal", "400", "500", "timeout-after-write"):
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
