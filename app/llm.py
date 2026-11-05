import os
import random
import time

import httpx


def article_url(slug: str) -> str:
    return f"{os.getenv('PUBLIC_BASE_URL', 'http://localhost:8000').rstrip('/')}/kb/{slug}"


def generate(message: str, articles: list[tuple]) -> str:
    context = "\n".join(f"{title}: {body} (джерело: {article_url(slug)})" for _, _, slug, title, body in articles)
    prompt = ("Ти оператор підтримки Orbita. Напиши коротку українську чернетку відповіді. "
              "Використовуй тільки наведені статті, додай повні посилання на використані статті. "
              "Якщо відповіді немає, чесно скажи, що потрібна перевірка оператором. "
              f"\nЗвернення: {message}\nСтатті:\n{context}")
    key = os.getenv("OPENAI_API_KEY", "")
    started = time.monotonic()
    try:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "messages": [{"role": "user", "content": prompt}]},
            timeout=35 if key else 4,
        )
        response.raise_for_status()
        if key:
            result = response.json()["choices"][0]["message"]["content"].strip()
            if result:
                return result
        else:
            raise RuntimeError("Provider response without API key is intentionally replaced")
    except Exception:
        if key:
            raise
        delay = random.uniform(float(os.getenv("MOCK_LLM_DELAY_MIN", "5")), float(os.getenv("MOCK_LLM_DELAY_MAX", "30")))
        time.sleep(max(0, delay - (time.monotonic() - started)))
        if articles:
            _, _, slug, title, body = articles[0]
            return f"Вітаємо! За вашим запитом може допомогти стаття «{title}»: {body}\n\nДжерело: {article_url(slug)}\n\nЯкщо проблема лишиться, повідомте нам деталі."
        return "Вітаємо! Поки не знайшли відповідної статті в базі знань. Оператор перевірить ваше звернення та підготує відповідь."
