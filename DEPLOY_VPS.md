# Розгортання на VPS без Docker

Сервіс запущено 6 листопада 2026 року. Docker на VPS не встановлювався. Конфігурація Docker Compose лишається в репозиторії для локального запуску та CI. Nginx, Node-проєкт і `/opt/other-project` не змінювалися.

## Що перевірено 6 листопада 2026 року

До змін через `ssh <VPS_HOST>` перевірено Ubuntu, Python 3.12 з `venv`, 1,9 GiB RAM і 19 GiB вільного диска. Nginx займав 80/443, чинний Node-проєкт — 3000, SSH — 22022. PostgreSQL, Docker, Podman і тунельні клієнти були відсутні. У `/srv/orbita-support` був чистий клон репозиторію на коміті `56fbf2e`; `/opt/other-project` належить іншому проєкту.

Перед інсталяцією `apt-get -s install postgresql-16` показав 11 нових пакетів, 0 оновлень і 0 видалень. Реальна інсталяція встановила тільки ці 11 пакетів. `apt autoremove` не виконувався. PostgreSQL слухає `127.0.0.1:5432` і `[::1]:5432`.

Orbita використовує лише `127.0.0.1:18000` (API) і `127.0.0.1:18001` (мок). Публічний трафік йде вихідним з'єднанням Cloudflare Tunnel, без нових відкритих вхідних портів.

## Ізольована схема

- Код і Python `venv`: `/srv/orbita-support` і `/srv/orbita-support/.venv`.
- Окремий системний користувач і роль PostgreSQL: `orbita`; окрема БД: `orbita_support`. З'єднання через локальний Unix socket з peer-автентифікацією, без відкритого порту БД назовні.
- Секрети: `/etc/orbita-support.env`, власник `root`, група `orbita`, права `0640`. Зразок: [deploy/vps.env.example](deploy/vps.env.example).
- Systemd units: `orbita-init`, `orbita-api`, `orbita-worker`, `orbita-mock`, `orbita-tunnel` з каталогу [deploy/systemd](deploy/systemd). API та мок слухають лише loopback. Воркер має 16 потоків; черга PostgreSQL зберігає пікові звернення, якщо генерація відстає.
- `cloudflared` 2026.10.7 завантажено як окремий бінарний файл у `/srv/orbita-support/.tools/cloudflared` і перевірено за SHA-256 `1f99fb518b83dec2ba8d870a7cc991d82a77e6196295a3d2754ba17ab9f91872` з [офіційного релізу](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.7). Він не встановлювався через системний пакетний менеджер.
- Quick Tunnel дає тимчасовий безкоштовний `*.trycloudflare.com` без акаунта. За [документацією Cloudflare](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) URL змінюється після зупинки процесу; гарантії безперервної роботи немає.

## Відтворення або оновлення

Нижче наведено орієнтир для відтворення на чистому сервері та подальшого оновлення. Перед повторенням перевірити `git status`, стан БД, вільні порти, RAM і диск. Не перезаписувати наявний `/etc/orbita-support.env` і не створювати вдруге роль чи БД.

1. Оновити лише ізольований клон після перевірки, що він чистий: `git -C /srv/orbita-support pull --ff-only origin main`.
2. Встановити PostgreSQL 16 через пакетний менеджер Ubuntu після `apt-get -s install postgresql-16`. Це єдина системна інсталяція для Orbita; Docker не потрібен. Перевірити, що кластер слухає лише локально та не конфліктує з наявними портами.
3. Створити системного користувача `orbita`, роль PostgreSQL `orbita` з `LOGIN` і БД `orbita_support` з власником `orbita`. Перевірити стандартну локальну peer-автентифікацію командою `sudo -u orbita psql -h /var/run/postgresql -d orbita_support -c 'SELECT 1'`. Якщо стандартне правило змінене, додати вузьке правило лише для цієї ролі та БД, не змінюючи правила інших користувачів.
4. Тимчасово надати `orbita` право створити `.venv` лише в `/srv/orbita-support`, створити його через `sudo -u orbita python3 -m venv /srv/orbita-support/.venv` і встановити залежності з `requirements.txt`. Повернути власника верхнього каталогу `root:root`, щоб `git pull` від root працював без глобального винятку `safe.directory`. Не запускати `pip` у системному Python.
5. Скопіювати `deploy/vps.env.example` у `/etc/orbita-support.env` з правами `root:orbita 0640`, задати випадкові `OPERATOR_PASSWORD` і `WEBHOOK_SECRET`. Для локальної перевірки задати `PUBLIC_BASE_URL=http://127.0.0.1:18000`; перед публічним тестом змінити на HTTPS-домен тунелю. API-ключ LLM необов'язковий.
6. Скопіювати `deploy/systemd/orbita-init.service`, `orbita-api.service`, `orbita-worker.service`, `orbita-mock.service` в `/etc/systemd/system/`, виконати `systemctl daemon-reload` і запустити `orbita-init`, потім три довготривалі сервіси. Перевірити `systemctl status` кожного та `curl -i http://127.0.0.1:18000/ready`.
7. Запустити інтеграційний тест тільки з локальними адресами: `BASE_URL=http://127.0.0.1:18000`, `MOCK_BASE_URL=http://127.0.0.1:18001`, `HELPDESK_ALLOWED_ORIGIN=http://127.0.0.1:18001`. Передати пароль і секрет у середовище тесту, не зберігаючи їх у shell history. Тест створює синтетичні записи в окремій БД Orbita.
8. Після локальної перевірки завантажити й перевірити `cloudflared`, встановити тільки `orbita-tunnel.service` та запустити його. Не змінювати конфігурацію nginx або чинні проєкти. Взяти URL із журналу, задати його в `PUBLIC_BASE_URL`, перезапустити `orbita-worker` і `orbita-api`. Публічний наскрізний тест запустити лише із синтетичними зверненнями.

Орієнтир команд для кроків 2–6 на чистому сервері (від root). Команди `createuser` і `createdb` виконуються лише якщо однойменних об'єктів ще немає. Файл секретів не перезаписувати, якщо він уже створений:

```sh
apt-get update
apt-get install -y postgresql-16
id orbita || useradd --system --home /srv/orbita-support --shell /usr/sbin/nologin orbita
sudo -u postgres createuser --login orbita
sudo -u postgres createdb --owner=orbita orbita_support
chown orbita:orbita /srv/orbita-support
sudo -u orbita python3 -m venv /srv/orbita-support/.venv
sudo -u orbita /srv/orbita-support/.venv/bin/python -m pip install --no-cache-dir -r /srv/orbita-support/requirements.txt
chown root:root /srv/orbita-support
install -o root -g orbita -m 0640 /srv/orbita-support/deploy/vps.env.example /etc/orbita-support.env
# Тут відредагувати три placeholders у /etc/orbita-support.env, згенерувавши секрети локально на VPS.
install -m 0644 /srv/orbita-support/deploy/systemd/orbita-init.service /srv/orbita-support/deploy/systemd/orbita-api.service /srv/orbita-support/deploy/systemd/orbita-worker.service /srv/orbita-support/deploy/systemd/orbita-mock.service /etc/systemd/system/
systemctl daemon-reload
systemctl start orbita-init
systemctl enable --now orbita-api orbita-worker orbita-mock
curl -i http://127.0.0.1:18000/ready
```

Для тунелю використано [офіційний бінарний реліз](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.7) і окремий unit `deploy/systemd/orbita-tunnel.service`. Зберігайте перевірений бінарний файл за шляхом `/srv/orbita-support/.tools/cloudflared` з правами `0755`; після `systemd-analyze verify` та `systemctl daemon-reload` запустіть `systemctl enable --now orbita-tunnel`. Для оновлення коду використовуйте `git pull --ff-only` лише в `/srv/orbita-support`, встановлюйте залежності лише у `.venv` та перезапускайте лише потрібні сервіси `orbita-*`.

## Доступ і перевірка

Актуальну адресу Quick Tunnel дізнайтеся на VPS без виведення секретів:

```sh
journalctl -u orbita-tunnel --no-pager | grep -Eo 'https://[a-z-]+\.trycloudflare\.com' | tail -n 1
```

- Вебхук: `<адреса>/webhooks/helpdesk` з `X-Webhook-Secret`; інтерфейс: `<адреса>/` з HTTP Basic користувачем `operator`. Для синтетичного вебхука на VPS поле `reply_url` має дорівнювати `http://127.0.0.1:18001/tickets/{ticket_id}/replies`: це адреса мока, яку перевіряє allowlist сервісу.
- Пароль оператора та секрет вебхука згенеровані випадково **на VPS** і лежать тільки в `/etc/orbita-support.env` (`root:orbita`, `0640`). Власник може переглянути потрібне значення у власному SSH-терміналі командами `sudo grep '^OPERATOR_PASSWORD=' /etc/orbita-support.env` і `sudo grep '^WEBHOOK_SECRET=' /etc/orbita-support.env`. Не надсилайте їх у чат і не додавайте до Git.
- Локальна перевірка: `curl -i http://127.0.0.1:18000/ready`; стан: `systemctl is-active postgresql orbita-api orbita-worker orbita-mock orbita-tunnel`; журнали: `journalctl -u orbita-worker -n 100 --no-pager`.
- Після запуску локальний і публічний `tests/integration.py` пройшли п'ять сценаріїв: одночасні дублікати вебхука, модерація з одним надсиланням, таймаут після запису, відновлення після `5xx`, ручний повтор після `400` та відхилення чернетки. У БД лише синтетичні звернення з `customer@example.com`.
- Публічні `/health` і `/ready` відповіли `200 OK`; операторський інтерфейс без авторизації відповів `401`. Після перезапуску API PID тунелю не змінився. Nginx і PM2 лишилися `active`.

Quick Tunnel є тимчасовим демо-доменом. Якщо `orbita-tunnel` перезапуститься, новий URL потрібно взяти з журналу, змінити `PUBLIC_BASE_URL` у `/etc/orbita-support.env` і перезапустити `orbita-worker`. Посилання в уже створених чернетках залишаться зі старим доменом. Для стабільного домену потрібен іменований тунель Cloudflare з власним акаунтом/доменом або інший сервіс зі сталим безкоштовним доменом. Резервне копіювання нової БД ще не налаштоване; до використання реальних даних його слід додати.

## Контроль змін і відкат

Усі нові процеси мають префікс `orbita-`; зупиняти або перезапускати лише їх. При проблемі зупинити `orbita-api`, `orbita-worker`, `orbita-mock` і `orbita-tunnel`. Дані БД та вміст інших проєктів не видаляти. Повне видалення БД чи PostgreSQL не входить в автоматичний відкат.

Гарантія від дублювання відповідей доведена лише для мока з ідемпотентним ключем. Перед підключенням реального хелпдеску потрібно підтвердити аналогічну підтримку на його боці.
