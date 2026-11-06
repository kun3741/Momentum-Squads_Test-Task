"""Run against a fresh PostgreSQL test database: python tests/rate_limit.py."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.db import LlmCall, SessionLocal
from app.worker import reserve_llm_slot


def main():
    if os.getenv("RATE_TEST_ALLOWED") != "1":
        raise SystemExit("Set RATE_TEST_ALLOWED=1 only for a disposable test database")
    with SessionLocal() as db:
        existing = db.scalar(select(func.count()).select_from(LlmCall))
    if existing:
        raise SystemExit("Use a fresh test database so the 60-call window starts empty")

    with ThreadPoolExecutor(max_workers=12) as pool:
        allowed = list(pool.map(lambda _: reserve_llm_slot(), range(100)))

    with SessionLocal() as db:
        stored = db.scalar(select(func.count()).select_from(LlmCall))
    assert sum(allowed) == 60, f"Allowed {sum(allowed)} of 100"
    assert stored == 60, f"Stored {stored} calls"
    print("PASS: 100 concurrent reservations yielded exactly 60 allowed LLM starts")


if __name__ == "__main__":
    main()
