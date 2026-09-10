#!/usr/bin/env python3
"""
Обмен Валют (obmen-vernadka.ru) — Flask-админка управления курсами валют.
Хранит курсы в SQLite, отдаёт публичный API /api/rates для сайта.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (Flask, Response, g, jsonify, redirect,
                   render_template, request, send_from_directory,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH  = BASE_DIR / "rates.db"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-please")

# ──────────────────────────────────────────────
# Базовые валюты (используются при первом запуске)
# ──────────────────────────────────────────────
DEFAULT_CURRENCIES = [
    {"code": "USD_BLUE",  "name": "Доллар США (синий)",      "flag": "🇺🇸", "sort_order": 1},
    {"code": "USD_WHITE", "name": "Доллар США (белый)",      "flag": "🇺🇸", "sort_order": 2},
    {"code": "EUR",       "name": "Евро",                    "flag": "🇪🇺", "sort_order": 3},
    {"code": "EUR500",    "name": "Евро (купюра 500 €)",     "flag": "🇪🇺", "sort_order": 4},
    {"code": "CNY",       "name": "Юань",                    "flag": "🇨🇳", "sort_order": 5},
]

# ──────────────────────────────────────────────
# БД
# ──────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT    NOT NULL UNIQUE,
            password TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rates (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            code       TEXT    NOT NULL UNIQUE,
            name       TEXT    NOT NULL,
            flag       TEXT    NOT NULL DEFAULT '',
            buy        REAL,
            sell       REAL,
            available  INTEGER NOT NULL DEFAULT 1,
            visible    INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT    NOT NULL DEFAULT ''
        );
    """)

    # Создаём дефолтного админа если нет ни одного пользователя
    row = db.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
    if row["cnt"] == 0:
        pwd = generate_password_hash(os.environ.get("ADMIN_PASSWORD", "admin123"))
        db.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                   ("admin", pwd))

    # Заполняем валюты при первом запуске
    for cur in DEFAULT_CURRENCIES:
        db.execute("""
            INSERT OR IGNORE INTO rates
                (code, name, flag, buy, sell, available, visible, sort_order, updated_at)
            VALUES (?, ?, ?, NULL, NULL, 0, 1, ?, '')
        """, (cur["code"], cur["name"], cur["flag"], cur["sort_order"]))

    db.commit()
    db.close()

# ──────────────────────────────────────────────
# Авторизация
# ──────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        error = "Неверный логин или пароль"
    return render_template("login.html", error=error)

@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ──────────────────────────────────────────────
# Главная страница админки
# ──────────────────────────────────────────────

@app.route("/admin")
@app.route("/admin/")
@login_required
def dashboard():
    db = get_db()
    rates = db.execute("SELECT * FROM rates ORDER BY sort_order, code").fetchall()
    return render_template("dashboard.html", rates=rates, username=session.get("username"))

# ──────────────────────────────────────────────
# Сохранение курсов (AJAX POST)
# ──────────────────────────────────────────────

@app.route("/admin/save", methods=["POST"])
@login_required
def save_rates():
    data = request.get_json(force=True) or {}
    items = data.get("rates", [])
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for item in items:
        code      = str(item.get("code", "")).strip().upper()
        available = bool(item.get("available", False))
        visible   = bool(item.get("visible", True))
        buy_raw   = item.get("buy")
        sell_raw  = item.get("sell")

        buy  = float(buy_raw)  if buy_raw  not in (None, "") else None
        sell = float(sell_raw) if sell_raw not in (None, "") else None

        db.execute("""
            UPDATE rates
            SET available = ?, visible = ?, buy = ?, sell = ?, updated_at = ?
            WHERE code = ?
        """, (int(available), int(visible), buy, sell, now, code))

    db.commit()
    return jsonify({"ok": True, "saved": len(items), "updated_at": now})

# ──────────────────────────────────────────────
# Добавление / удаление валюты
# ──────────────────────────────────────────────

@app.route("/admin/currency/add", methods=["POST"])
@login_required
def add_currency():
    db = get_db()
    code = request.form.get("code", "").strip().upper()
    name = request.form.get("name", "").strip()
    flag = request.form.get("flag", "").strip()
    if not code or not name:
        return jsonify({"ok": False, "error": "Код и название обязательны"}), 400
    max_order = db.execute("SELECT MAX(sort_order) as m FROM rates").fetchone()["m"] or 0
    try:
        db.execute("""
            INSERT INTO rates (code, name, flag, available, visible, sort_order, updated_at)
            VALUES (?, ?, ?, 0, 1, ?, '')
        """, (code, name, flag, max_order + 1))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": f"Валюта {code} уже существует"}), 409
    return redirect(url_for("dashboard"))

@app.route("/admin/currency/delete/<code>", methods=["POST"])
@login_required
def delete_currency(code):
    db = get_db()
    db.execute("DELETE FROM rates WHERE code = ?", (code.upper(),))
    db.commit()
    return redirect(url_for("dashboard"))

# ──────────────────────────────────────────────
# Смена пароля
# ──────────────────────────────────────────────

@app.route("/admin/change-password", methods=["POST"])
@login_required
def change_password():
    old = request.form.get("old_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if not check_password_hash(user["password"], old):
        return render_template("dashboard.html",
                               rates=db.execute("SELECT * FROM rates ORDER BY sort_order").fetchall(),
                               username=session.get("username"),
                               pw_error="Старый пароль неверен")
    if new != confirm or len(new) < 6:
        return render_template("dashboard.html",
                               rates=db.execute("SELECT * FROM rates ORDER BY sort_order").fetchall(),
                               username=session.get("username"),
                               pw_error="Пароли не совпадают или слишком короткий (мин. 6 символов)")
    db.execute("UPDATE users SET password = ? WHERE id = ?",
               (generate_password_hash(new), session["user_id"]))
    db.commit()
    return render_template("dashboard.html",
                           rates=db.execute("SELECT * FROM rates ORDER BY sort_order").fetchall(),
                           username=session.get("username"),
                           pw_ok="Пароль успешно изменён")

# ──────────────────────────────────────────────
# Публичный API — отдаёт rates.json для сайта
# ──────────────────────────────────────────────

@app.route("/api/rates")
def api_rates():
    db = get_db()
    rows = db.execute("""
        SELECT code, name, flag, buy, sell, available, updated_at
        FROM rates
        WHERE visible = 1
        ORDER BY sort_order, code
    """).fetchall()

    rates = []
    for r in rows:
        rates.append({
            "code":      r["code"],
            "name":      r["name"],
            "flag":      r["flag"],
            "available": bool(r["available"]),
            "buy":       r["buy"],
            "sell":      r["sell"],
        })

    last_update = ""
    if rows:
        dates = [r["updated_at"] for r in rows if r["updated_at"]]
        if dates:
            last_update = max(dates)

    payload = {
        "updated_at": last_update or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":     "admin",
        "rates":      rates,
    }

    resp = Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json"
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

# ──────────────────────────────────────────────
# Запуск
# ──────────────────────────────────────────────

SITE_ROOT = BASE_DIR.parent

# ──────────────────────────────────────────────
# Раздача статичного сайта
# ──────────────────────────────────────────────

@app.route("/")
def site_index():
    return send_from_directory(SITE_ROOT, "index.html")

@app.route("/assets/<path:filename>")
def site_assets(filename):
    return send_from_directory(SITE_ROOT / "assets", filename)

@app.route("/scripts/<path:filename>")
def site_scripts(filename):
    return send_from_directory(SITE_ROOT / "scripts", filename)

@app.route("/<path:filename>")
def site_static(filename):
    return send_from_directory(SITE_ROOT, filename)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)