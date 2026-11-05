import re

from sqlalchemy import select

from .db import Article, SessionLocal


# Fictional product: Orbita, a small reporting platform.
ARTICLES = [
    ("pdf-export", "Експорт звіту в PDF", "Відкрийте звіт в Orbita, натисніть «Експорт» → «PDF». Якщо файл не з'явився, дозвольте завантаження в браузері та повторіть спробу. Для великих звітів дочекайтеся завершення формування.", "pdf експорт звіт завантажити файл export report"),
    ("csv-export", "Експорт даних у CSV", "На сторінці звіту виберіть «Експорт» → «CSV». Файл містить поточні фільтри. Для коректного відображення кирилиці відкривайте його як UTF-8.", "csv експорт дані таблиця кодування"),
    ("password-reset", "Скидання пароля", "На сторінці входу натисніть «Забули пароль?», введіть адресу облікового запису й відкрийте лист для скидання. Посилання діє 30 хвилин. Перевірте папку спаму, якщо листа немає.", "пароль вхід логін лист reset password"),
    ("team-invite", "Запрошення колеги", "Адміністратор може відкрити «Налаштування» → «Команда» → «Запросити», вказати email і роль. Запрошення дійсне 7 днів.", "команда запросити користувач доступ роль email"),
    ("billing", "Рахунки та оплата", "Рахунки доступні власнику робочого простору в «Налаштування» → «Оплата» → «Рахунки». Там можна змінити платіжну картку. Зміна тарифу набуває чинності на початку наступного розрахункового періоду.", "оплата рахунок тариф картка billing invoice"),
    ("data-sync", "Оновлення даних", "Orbita синхронізує підключені джерела щогодини. Час останнього оновлення видно над звітом. Якщо дані застаріли більш ніж на 2 години, відкрийте «Джерела даних» і перевірте стан підключення.", "синхронізація дані оновлення джерело звіт"),
    ("filters", "Фільтри звіту", "Фільтри періоду та команди розташовані над звітом. Після зміни натисніть «Застосувати». Експорт у PDF і CSV використовує вибрані фільтри.", "фільтр період команда звіт дата"),
    ("api-token", "API токен", "Адміністратор створює токен у «Налаштування» → «Інтеграції» → «API». Скопіюйте його одразу: повторно значення не показується. Якщо токен втрачено, відкличте його і створіть новий.", "api токен інтеграція ключ доступ"),
]


def seed():
    with SessionLocal.begin() as db:
        existing = set(db.scalars(select(Article.slug)).all())
        for slug, title, body, keywords in ARTICLES:
            if slug not in existing:
                db.add(Article(slug=slug, title=title, body=body, keywords=keywords))


def find_relevant(message: str, limit: int = 3):
    words = set(re.findall(r"[\w]+", message.casefold()))
    with SessionLocal() as db:
        articles = db.scalars(select(Article)).all()
        scored = []
        for article in articles:
            terms = set(re.findall(r"[\w]+", (article.title + " " + article.keywords).casefold()))
            score = len(words & terms)
            if score:
                scored.append((score, article.id, article.slug, article.title, article.body))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[:limit]
