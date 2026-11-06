# Agent notes

This repository is a staged take-home backend exercise. The owner reviews each stage before the next one. Do not commit or deploy changes without the owner's instruction for that stage.

## Contract and invariants

- The webhook acknowledges only after the event and ticket are committed to PostgreSQL. Its normal response is `202` within two seconds.
- `event_id` and `ticket_id` are unique. Concurrent duplicate deliveries must not produce duplicate tickets.
- Generation and sending run in the worker. Claims use PostgreSQL row locks and expiring leases so crashed workers can be retried.
- The service reserves at most 60 LLM call starts in any rolling 60-second window across workers.
- A reply uses a stable `Idempotency-Key` per ticket. The mock helpdesk deduplicates it. A real helpdesk must provide equivalent server-side deduplication to guarantee no duplicate customer replies after an ambiguous timeout.
- Only the configured helpdesk origin can receive replies. Keep this allowlist when changing the integration.
- Never put credentials in Git. `.env` is ignored; `.env.example` contains local development defaults only.

## Verification

- `python -m compileall -q app tests`
- `python -m pytest -q tests/test_contract.py`
- With Docker available: `docker compose up --build -d`, then `python tests/integration.py`.
- Capacity scripts require a disposable database and explicit `RATE_TEST_ALLOWED=1` or `LOAD_TEST_ALLOWED=1`; never point them at a live service.
- Report which checks actually ran. Local syntax checks do not establish that the PostgreSQL and HTTP paths work end to end.
