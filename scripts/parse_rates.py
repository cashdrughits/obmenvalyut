#!/usr/bin/env python3
"""
Читает последнее сообщение с тегом #курсы из публичного Telegram-канала
(через веб-версию t.me/s/<channel>, без API и без токена бота)
и обновляет assets/rates.json.

Формат сообщения в канале, который публикует владелец обменника:

    #курсы
    USD_BLUE 82.00 83.00
    USD_WHITE 79.00 81.50
    EUR 94.00 95.00
    CNY -

Строка с курсом:      КОД ПОКУПКА ПРОДАЖА   (например USD_BLUE 82.00 83.00)
Строка "нет в наличии": КОД -                (или "нет" / "недоступно")
  — сайт вместо цифр покажет заглушку "уточняйте по телефону".

Список валют и порядок их появления на сайте задаются самим сообщением:
какие коды пришли в последнем сообщении с #курсы — те и показываются,
в том же порядке.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
RATES_FILE = REPO_ROOT / "assets" / "rates.json"

RATES_HASHTAG = "#курсы"

# Человекочитаемые названия и флаги для известных кодов валют этого обменника.
# Если владелец напишет код, которого здесь нет, сайт всё равно покажет его
# (просто без флага, а название = сам код) — можно дополнить словарь позже.
CURRENCY_INFO = {
    "USD_BLUE": {"name": "Доллар США (синий)", "flag": "🇺🇸"},
    "USD_WHITE": {"name": "Доллар США (белый)", "flag": "🇺🇸"},
    "EUR": {"name": "Евро", "flag": "🇪🇺"},
    "CNY": {"name": "Юань", "flag": "🇨🇳"},
}

RATE_LINE_RE = re.compile(
    r"^\s*([A-Za-zА-Яа-я_]{2,12})\s+([0-9]+[.,][0-9]+)\s+([0-9]+[.,][0-9]+)\s*$"
)
UNAVAILABLE_LINE_RE = re.compile(
    r"^\s*([A-Za-zА-Яа-я_]{2,12})\s+(-|нет|недоступ\w*)\s*$", re.IGNORECASE
)


def fetch_channel_html(channel: str) -> str:
    url = f"https://t.me/s/{channel}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text


def find_last_rates_message(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    message_blocks = soup.select("div.tgme_widget_message_text")

    last_match = None
    for block in message_blocks:
        text = block.get_text("\n").strip()
        if RATES_HASHTAG.lower() in text.lower():
            last_match = text  # t.me/s отдаёт сообщения от старых к новым

    return last_match


def parse_rates(message_text: str) -> list[dict]:
    rates = []
    for raw_line in message_text.splitlines():
        code = None
        entry = None

        m = RATE_LINE_RE.match(raw_line)
        if m:
            code, buy_raw, sell_raw = m.groups()
            code = code.upper()
            entry = {
                "available": True,
                "buy": float(buy_raw.replace(",", ".")),
                "sell": float(sell_raw.replace(",", ".")),
            }
        else:
            m = UNAVAILABLE_LINE_RE.match(raw_line)
            if m:
                code = m.group(1).upper()
                entry = {"available": False, "buy": None, "sell": None}

        if not entry:
            continue

        info = CURRENCY_INFO.get(code, {})
        entry["code"] = code
        entry["name"] = info.get("name", code)
        entry["flag"] = info.get("flag", "")
        rates.append(entry)

    return rates


def main() -> int:
    channel = os.environ.get("TELEGRAM_CHANNEL")
    if not channel:
        print("::error::Переменная окружения TELEGRAM_CHANNEL не задана", file=sys.stderr)
        return 1

    html = fetch_channel_html(channel)
    message_text = find_last_rates_message(html)

    if not message_text:
        print(
            f"Сообщение с тегом {RATES_HASHTAG} не найдено в канале @{channel}. "
            "rates.json не изменён.",
            file=sys.stderr,
        )
        return 0

    rates = parse_rates(message_text)
    if not rates:
        print(
            "Сообщение с тегом найдено, но ни одна строка не распозналась. "
            "Проверьте формат: 'USD_BLUE 82.00 83.00' или 'CNY -'.",
            file=sys.stderr,
        )
        return 0

    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": f"telegram:@{channel}",
        "rates": rates,
    }

    RATES_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Обновлено {len(rates)} валют из канала @{channel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
