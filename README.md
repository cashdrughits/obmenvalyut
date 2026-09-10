# Деплой «Обмен Валют» (obmen-vernadka.ru) на сервер

Та же схема, что и для ОперКассы: статический сайт + Flask-админка на SQLite.
Это отдельный сервер, поэтому все пути и порты — стандартные, ничего
разводить не нужно.

## Структура проекта

```
obmen-vernadka/
├── index.html               ← фронтенд сайта (грузит /api/rates)
├── assets/
│   ├── favicon.png
│   └── hero-photo.png
├── admin/
│   ├── app.py                ← Flask-приложение
│   ├── init_db.py            ← первичная инициализация БД
│   ├── requirements.txt
│   ├── rates.db               ← создаётся автоматически
│   └── templates/
│       ├── login.html
│       └── dashboard.html
├── obmen-vernadka.service    ← systemd-unit
└── nginx.conf                ← конфиг nginx
```

> Раньше курсы обновлялись через `scripts/parse_rates.py` (парсинг Telegram-канала
> в GitHub Actions), а сайт хостился на GitHub Pages (отсюда файл `CNAME`).
> Теперь курсы редактируются вручную через `/admin`, как в ОперКассе — GitHub
> Pages и Action с парсером для этого больше не нужны (см. пункт 8 ниже).

---

## Установка на Ubuntu/Debian сервер

### 1. Загрузить проект на сервер

Папку можно выбрать любую — `/var/www/obmen-vernadka`, `/opt/obmen-vernadka`,
`/home/ubuntu/obmen-vernadka` и т.д. Пример с `/opt`:

```bash
git clone https://github.com/твой-юзер/твой-репо-vernadka.git /opt/obmen-vernadka
```

> Если репо приватное, настрой deploy key:
> `ssh-keygen -t ed25519 -f ~/.ssh/deploy_key` → добавь публичный ключ в GitHub → Settings → Deploy keys.

### 2. Виртуальное окружение и зависимости

```bash
cd /opt/obmen-vernadka
python3 -m venv venv
source venv/bin/activate
pip install -r admin/requirements.txt
```

### 3. Инициализировать БД и создать первого admin

```bash
cd /opt/obmen-vernadka/admin

# Дефолтный пароль admin123 (смените после входа!)
python init_db.py

# Или сразу с нужным паролем:
ADMIN_PASSWORD=ВашПароль python init_db.py
```

### 4. Создать папку логов ЗАРАНЕЕ

На ОперКассе этот шаг забыли — сервис падал с `error.log isn't writable`.
Делаем сразу, чтобы не наступать на те же грабли:

```bash
mkdir -p /var/log/obmen-vernadka
chown -R www-data:www-data /var/log/obmen-vernadka
```

### 5. Выставить владельца проекта на www-data

Сервис работает от `www-data`, а gunicorn должен уметь писать в `admin/rates.db`
(SQLite в режиме WAL пишет `-wal`/`-shm` файлы даже при обычном чтении).
Тоже делаем сразу, чтобы не ловить `attempt to write a readonly database`:

```bash
chown -R www-data:www-data /opt/obmen-vernadka
```

### 6. Отредактировать и установить systemd-сервис

Если выбрали не `/opt`, поправь пути в `obmen-vernadka.service`:

```bash
nano /opt/obmen-vernadka/obmen-vernadka.service
```

```ini
WorkingDirectory=/opt/obmen-vernadka/admin
ExecStart=/opt/obmen-vernadka/venv/bin/gunicorn \
```

Также **обязательно** замени `SECRET_KEY` на случайную строку:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Затем установи сервис:

```bash
cp /opt/obmen-vernadka/obmen-vernadka.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable obmen-vernadka
systemctl start obmen-vernadka
systemctl status obmen-vernadka
```

Статус должен быть `active (running)`, а не `activating (auto-restart)`.
Если не так — сразу смотрите `tail -n 50 /var/log/obmen-vernadka/error.log`.

### 7. Настроить nginx

```bash
cp /opt/obmen-vernadka/nginx.conf /etc/nginx/sites-available/obmen-vernadka
ln -s /etc/nginx/sites-available/obmen-vernadka /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

### 8. DNS и отключение старой GitHub Pages-схемы

- В DNS-панели домена `obmen-vernadka.ru` поменяйте A-запись так, чтобы она
  указывала на IP этого сервера (раньше она, судя по `CNAME`, указывала на
  GitHub Pages).
- В репозитории на GitHub отключите workflow, который запускал
  `scripts/parse_rates.py` (Settings → Actions, либо удалите/закомментируйте
  сам `.yml`-файл workflow). Он больше не нужен — сайт теперь берёт курсы из
  `/api/rates`, а не из `assets/rates.json`.
- Файл `CNAME` для GitHub Pages можно удалить из репозитория, если сайт
  полностью переезжает на VPS.

### 9. SSL через certbot

```bash
apt install certbot python3-certbot-nginx
certbot --nginx -d obmen-vernadka.ru -d www.obmen-vernadka.ru
```
После этого раскомментируйте HTTPS-блок в `nginx.conf`.

### 10. Обновление сайта в будущем

```bash
cd /opt/obmen-vernadka
git pull
systemctl restart obmen-vernadka
```

---

## Использование

| URL | Что |
|-----|-----|
| `https://obmen-vernadka.ru/` | Публичный сайт |
| `https://obmen-vernadka.ru/api/rates` | JSON с курсами (для сайта) |
| `https://obmen-vernadka.ru/admin` | Вход в панель управления |
| `https://obmen-vernadka.ru/admin/logout` | Выход |

### Как менять курсы

1. Зайти на `/admin`
2. Ввести логин/пароль
3. Изменить покупку/продажу, переключить «В наличии» или «Показывать»
4. Нажать **«Сохранить курсы»**

Сайт подхватит изменения мгновенно (страница опрашивает `/api/rates` каждые 60 секунд).

### Переменные окружения (в obmen-vernadka.service)

| Переменная | Описание |
|---|---|
| `SECRET_KEY` | Ключ сессий Flask — случайная строка, **обязательно смените** |
| `ADMIN_PASSWORD` | Только для `init_db.py`, после инициализации не нужна |
| `PORT` | Порт gunicorn (по умолчанию 5000) |

---

## Чек-лист «если снова 502 / 500» (уже проходили на ОперКассе)

1. `systemctl status obmen-vernadka` — если не `active (running)`, идите в лог.
2. `journalctl -u obmen-vernadka -n 50 --no-pager` или `tail -n 50 /var/log/obmen-vernadka/error.log`.
3. `error.log isn't writable` → не выполнен пункт 4 (создать и `chown` папку логов).
4. `attempt to write a readonly database` → не выполнен пункт 5 (`chown -R www-data:www-data /opt/obmen-vernadka`).
5. Пути в `obmen-vernadka.service` не совпадают с тем, куда реально склонировали репозиторий.

## Быстрая генерация SECRET_KEY

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```