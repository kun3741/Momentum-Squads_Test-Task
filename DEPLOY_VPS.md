# План запуску на VPS без Docker

Це підготовлена інструкція для наступного етапу. Сервіс на VPS ще не запущено. Docker на VPS не встановлюємо. Конфігурація Docker Compose лишається в репозиторії для локального запуску та CI.

## Що перевірено 6 листопада 2026 року

Через `ssh <VPS_HOST>` виконано лише команди читання. На сервері Ubuntu, Python 3.12 з `venv`, 1,9 GiB RAM (приблизно 1,3 GiB доступно), 19 GiB вільного диска. Nginx займає 80/443, чинний Node-проєкт — 3000, SSH — 22022. PostgreSQL, Docker, Podman і тунельні клієнти відсутні. У `/srv/orbita-support` є чистий клон репозиторію на старішому коміті `56fbf2e`; `/opt/other-project` належить іншому проєкту.

Поточний `apt-get -s install postgresql-16` показав 11 нових пакетів, 0 оновлень і 0 видалень. Це лише симуляція; перед реальною інсталяцією перевірку потрібно повторити, бо стан пакетів може змінитися. `apt autoremove` не виконувати.

Для Orbita виділено порти `127.0.0.1:18000` (API) і `127.0.0.1:18001` (мок). Вони зараз вільні. Наявні nginx, Node-проєкт, `/opt/other-project`, їхні файли й порти не потрібно змінювати.

## Ізольована схема

- Код і Python `venv`: `/srv/orbita-support` і `/srv/orbita-support/.venv`.
- Окремий системний користувач і роль PostgreSQL: `orbita`; окрема БД: `orbita_support`. З'єднання через локальний Unix socket з peer-автентифікацією, без відкритого порту БД назовні.
- Секрети: `/etc/orbita-support.env`, власник `root`, група `orbita`, права `0640`. Зразок: [deploy/vps.env.example](deploy/vps.env.example).
- Нові systemd units: `orbita-init`, `orbita-api`, `orbita-worker`, `orbita-mock` з каталогу [deploy/systemd](deploy/systemd). API та мок слухають лише loopback. Воркер має 16 потоків; черга PostgreSQL зберігає пікові звернення, якщо генерація відстає.
- Публічний HTTPS-тунель налаштовується окремим наступним етапом. `PUBLIC_BASE_URL` має бути його стабільним доменом до створення публічних чернеток.

## Порядок майбутнього запуску

Ці команди **ще не виконувалися**. Перед виконанням знову перевірити `git status`, вільні порти, RAM і дисковий простір: стан сервера може змінитися.

1. Оновити лише ізольований клон після перевірки, що він чистий: `git -C /srv/orbita-support pull --ff-only origin main`.
2. Встановити PostgreSQL 16 через пакетний менеджер Ubuntu. Це єдина запланована інсталяція системного сервісу; Docker не потрібен. Перевірити, що кластер слухає лише локально та не конфліктує з наявними портами.
3. Створити системного користувача `orbita`, роль PostgreSQL `orbita` з `LOGIN` і БД `orbita_support` з власником `orbita`. Перевірити стандартну локальну peer-автентифікацію командою `sudo -u orbita psql -h /var/run/postgresql -d orbita_support -c 'SELECT 1'`. Якщо стандартне правило змінене, додати вузьке правило лише для цієї ролі та БД, не змінюючи правила інших користувачів.
4. Надати `orbita` право створити `.venv` лише в `/srv/orbita-support` та створити його через `sudo -u orbita python3 -m venv /srv/orbita-support/.venv`. Встановити залежності в нього з `requirements.txt`. Не запускати `pip` у системному Python.
5. Скопіювати `deploy/vps.env.example` у `/etc/orbita-support.env` з правами `root:orbita 0640`, задати випадкові `OPERATOR_PASSWORD` і `WEBHOOK_SECRET`. Для локальної перевірки задати `PUBLIC_BASE_URL=http://127.0.0.1:18000`; перед публічним тестом змінити на HTTPS-домен тунелю. API-ключ LLM необов'язковий.
6. Скопіювати лише чотири файли `deploy/systemd/orbita-*.service` в `/etc/systemd/system/`, виконати `systemctl daemon-reload` і запустити `orbita-init`, потім `orbita-api`, `orbita-worker`, `orbita-mock`. Увімкнути автозапуск трьох довготривалих сервісів. Перевірити `systemctl status` кожного та `curl -i http://127.0.0.1:18000/ready`.
7. Запустити інтеграційний тест тільки з локальними адресами: `BASE_URL=http://127.0.0.1:18000`, `MOCK_BASE_URL=http://127.0.0.1:18001`, `HELPDESK_ALLOWED_ORIGIN=http://127.0.0.1:18001`. Передати пароль і секрет у середовище тесту, не зберігаючи їх у shell history. Тест створює синтетичні записи в окремій БД Orbita.
8. Після локальної перевірки встановити тунельний клієнт і налаштувати лише перенаправлення на `127.0.0.1:18000`. Не змінювати конфігурацію nginx або чинні проєкти. Перевірити зовнішні `/health`, `/ready`, вебхук та інтерфейс оператора. Оновити `PUBLIC_BASE_URL` на стабільний HTTPS-домен і перезапустити лише Orbita-сервіси.

Орієнтир команд для кроків 2–6 після перевірки поточного стану (від root). Команди `createuser` і `createdb` виконуються лише якщо однойменних об'єктів ще немає. Файл секретів не перезаписувати, якщо він уже створений:

```sh
apt-get update
apt-get install -y postgresql-16
id orbita || useradd --system --home /srv/orbita-support --shell /usr/sbin/nologin orbita
sudo -u postgres createuser --login orbita
sudo -u postgres createdb --owner=orbita orbita_support
chown orbita:orbita /srv/orbita-support
sudo -u orbita python3 -m venv /srv/orbita-support/.venv
sudo -u orbita /srv/orbita-support/.venv/bin/python -m pip install -r /srv/orbita-support/requirements.txt
install -o root -g orbita -m 0640 /srv/orbita-support/deploy/vps.env.example /etc/orbita-support.env
# Тут відредагувати три placeholders у /etc/orbita-support.env, згенерувавши секрети локально на VPS.
install -m 0644 /srv/orbita-support/deploy/systemd/orbita-*.service /etc/systemd/system/
systemctl daemon-reload
systemctl start orbita-init
systemctl enable --now orbita-api orbita-worker orbita-mock
curl -i http://127.0.0.1:18000/ready
```

Для зміни конфігурації редагувати лише `/etc/orbita-support.env`, потім перезапускати потрібні `orbita-*` сервіси. Значення секретів не додавати в Git або командний рядок процесу. Перед установленням пакета ще раз перевірити, що `apt` не збирається видаляти чи замінювати пакети, потрібні іншим проєктам.

## Контроль змін і відкат

Усі нові процеси мають префікс `orbita-`; зупиняти або перезапускати лише їх. При проблемі зупинити `orbita-api`, `orbita-worker`, `orbita-mock` і тунель Orbita. Дані БД та вміст інших проєктів не видаляти. Встановлення PostgreSQL є системною зміною, тож перед ним окремо перевірити її вплив на пам'ять і доступні оновлення пакетів. Повне видалення БД чи пакетів не входить в автоматичний відкат.

Гарантія від дублювання відповідей доведена лише для мока з ідемпотентним ключем. Перед підключенням реального хелпдеску потрібно підтвердити аналогічну підтримку на його боці.
