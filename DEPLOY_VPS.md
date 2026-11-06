# Orbita на VPS

Сервіс працює на [https://orbita.104-207-90-199.sslip.io/](https://orbita.104-207-90-199.sslip.io/). Вебхук: [https://orbita.104-207-90-199.sslip.io/webhooks/helpdesk](https://orbita.104-207-90-199.sslip.io/webhooks/helpdesk). [sslip.io](https://sslip.io/) повертає IP, закодований у hostname; тут це `104.207.90.199`. Акаунт DNS-сервісу не потрібен. Адреса лишається тією самою після перезапуску процесів, доки не зміниться IP VPS або доступність sslip.io.

HTTPS забезпечує окремий сертифікат Let's Encrypt для цього hostname. Сертифікат випущено 7 листопада 2026 року, він чинний до 4 лютого 2027 року. `certbot.timer` і [hook](deploy/certbot/orbita-nginx-reload) поновлюють його та перечитують nginx лише після поновлення сертифіката Orbita. `certbot renew --cert-name orbita.104-207-90-199.sslip.io --dry-run --non-interactive` пройшов. Certbot може додати кількахвилинну випадкову затримку до ручної перевірки.

## Ізоляція від інших проєктів

- Docker на VPS не встановлювався. Код: `/srv/orbita-support`, Python-залежності: `.venv` у цьому каталозі.
- PostgreSQL 16 має окремі роль `orbita` та БД `orbita_support`, слухає лише локально. Мок хелпдеску слухає `127.0.0.1:18001`, API — `127.0.0.1:18000`.
- Довготривалі systemd-сервіси: `orbita-api`, `orbita-worker`, `orbita-mock`. Ініціалізація БД — `orbita-init`. Старий `orbita-tunnel` вимкнений; Quick Tunnel більше не використовується.
- Nginx має окремий файл `/etc/nginx/sites-available/orbita-support` і symlink у `sites-enabled`. У ньому тільки `server_name orbita.104-207-90-199.sslip.io` та proxy на `127.0.0.1:18000`. [HTTP](deploy/nginx/orbita-http.conf) та [HTTPS](deploy/nginx/orbita-https.conf) шаблони зберігаються в Git.
- Секрети лежать лише в `/etc/orbita-support.env` з правами `root:orbita 0640`. Його зразок — [deploy/vps.env.example](deploy/vps.env.example); реальний файл не в Git.

Перед першим nginx reload і після кожної зміни виконано `nginx -t`. Інші сайти на VPS залишилися доступними після оновлення конфігурації. Orbita `/health` і `/ready` повертають `200`, інтерфейс без HTTP Basic — `401`.

## Доступ оператора й тестовий вебхук

Інтерфейс: [https://orbita.104-207-90-199.sslip.io/](https://orbita.104-207-90-199.sslip.io/), користувач HTTP Basic — `operator`. Вебхук потребує `X-Webhook-Secret`. Власник може переглянути відповідні значення **у власному SSH-терміналі**:

```sh
ssh <VPS_HOST>
sudo grep '^OPERATOR_PASSWORD=' /etc/orbita-support.env
sudo grep '^WEBHOOK_SECRET=' /etc/orbita-support.env
```

Не надсилайте значення секретів у чат. Для синтетичного звернення `reply_url` має бути `http://127.0.0.1:18001/tickets/T-DEMO-1/replies`; цей внутрішній origin дозволений сервісом. Публічна адреса потрібна для `POST /webhooks/helpdesk`, але мок приймає відповіді лише на loopback VPS.

Після перемикання на sslip.io повний `tests/integration.py` пройшов через публічний HTTPS: 12 одночасних дублікатів вебхука, модерація з однією відповіддю, повтор після таймауту, відновлення після `5xx`, ручний повтор після `400`, відхилення чернетки. Нова чернетка містила посилання `https://orbita.104-207-90-199.sslip.io/kb/pdf-export`. У БД поки тільки синтетичні звернення.

## Обслуговування

```sh
ssh <VPS_HOST>
systemctl is-active nginx postgresql orbita-api orbita-worker orbita-mock
curl -i http://127.0.0.1:18000/ready
journalctl -u orbita-worker -n 100 --no-pager
nginx -t
```

Для оновлення коду спочатку перевірте `git -C /srv/orbita-support status --short`, потім використовуйте `git -C /srv/orbita-support pull --ff-only origin main`; Python-пакети встановлюйте лише в `/srv/orbita-support/.venv`. Перезапускайте тільки потрібні `orbita-*` сервіси. Якщо зміниться nginx-шаблон Orbita, перевірте `nginx -t` **до** `systemctl reload nginx` і потім перевірте доступність сервісу та інших сайтів на VPS.

`PUBLIC_BASE_URL=https://orbita.104-207-90-199.sslip.io` уже задано у конфігу VPS. Якщо IP зміниться, потрібно обрати новий hostname, випустити для нього окремий сертифікат, оновити vhost і `PUBLIC_BASE_URL`. Резервне копіювання `orbita_support` ще не налаштоване; до роботи з реальними клієнтськими даними його треба додати. Реальний хелпдеск також має підтримувати ідемпотентне надсилання за сталим ключем.
