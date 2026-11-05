import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app import llm
from app import main
from fastapi import HTTPException
from app.main import check_review_token, review_token
from app.worker import valid_reply_url


def test_no_key_still_calls_provider_and_uses_delayed_fallback(monkeypatch):
    calls = []
    sleeps = []

    def provider(*args, **kwargs):
        calls.append((args, kwargs))
        raise httpx.HTTPStatusError("401", request=httpx.Request("POST", args[0]), response=httpx.Response(401))

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setattr(llm.httpx, "post", provider)
    monkeypatch.setattr(llm.random, "uniform", lambda low, high: 5)
    monkeypatch.setattr(llm.time, "monotonic", lambda: 0)
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    answer = llm.generate("PDF", [(1, 1, "pdf-export", "PDF export", "Open export")])

    assert len(calls) == 1
    assert calls[0][0][0] == "https://api.openai.com/v1/chat/completions"
    assert sleeps == [5]
    assert "https://example.test/kb/pdf-export" in answer


def test_real_model_draft_gets_retrieved_article_links(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "Відкрийте експорт звіту."}}]}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setattr(llm.httpx, "post", lambda *args, **kwargs: Response())
    answer = llm.generate("PDF", [(1, 1, "pdf-export", "Експорт PDF", "Відкрийте експорт")])

    assert "Відкрийте експорт звіту." in answer
    assert "Експорт PDF: https://example.test/kb/pdf-export" in answer


def test_reply_destination_must_match_configured_ticket(monkeypatch):
    monkeypatch.setenv("HELPDESK_ALLOWED_ORIGIN", "http://mock-helpdesk:8001")
    assert valid_reply_url("http://mock-helpdesk:8001/tickets/T-1/replies", "T-1")
    assert not valid_reply_url("http://evil.test/tickets/T-1/replies", "T-1")
    assert not valid_reply_url("http://mock-helpdesk:8001/tickets/T-2/replies", "T-1")
    assert not valid_reply_url("http://mock-helpdesk:8001/tickets/T-1/replies?redirect=evil", "T-1")
    assert not valid_reply_url("http://mock-helpdesk:bad/tickets/T-1/replies", "T-1")


def test_review_action_tokens_are_distinct(monkeypatch):
    monkeypatch.setenv("OPERATOR_PASSWORD", "test-secret")
    approve = review_token(17, "approve")
    reject = review_token(17, "reject")
    assert approve != reject
    check_review_token(17, "approve", approve)
    try:
        check_review_token(17, "approve", reject)
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Wrong action token was accepted")


def test_webhook_returns_retryable_error_when_database_is_unavailable(monkeypatch):
    class UnavailableSessions:
        def begin(self):
            raise OperationalError("connect", {}, Exception("database unavailable"))

    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("HELPDESK_ALLOWED_ORIGIN", "http://mock-helpdesk:8001")
    monkeypatch.setattr(main, "SessionLocal", UnavailableSessions())
    body = main.WebhookIn(
        event_id="evt-db-down",
        ticket_id="T-DB-DOWN",
        customer_email="user@example.com",
        message="PDF export failed",
        reply_url="http://mock-helpdesk:8001/tickets/T-DB-DOWN/replies",
    )
    with pytest.raises(HTTPException) as error:
        main.webhook(body, x_webhook_secret="test-secret")
    assert error.value.status_code == 503
    assert "retry" in error.value.detail
