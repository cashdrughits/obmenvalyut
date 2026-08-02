#!/usr/bin/env python3
"""
Читает последнее сообщение с тегом #курсы из публичного Telegram-канала
(через веб-версию t.me/s/<channel>, без API и без токена бота)
и обновляет assets/rates.json.

Формат сообщения в канале, который должен публиковать владелец обменника:

    #курсы
    USD 92.10 93.50
    EUR 99.00 101.20
    USDT 91.50 93.00

Строка: КОД_ВАЛЮТЫ ПОКУПКА ПРОДАЖА (через пробел, разделитель дробной части — точка).
Название валюты сайт берёт из справочника CURRENCY_NAMES ниже, а если код
не найден в справочнике — использует сам код в качестве названия.
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

# Тег, по которому скрипт ищет "то самое" сообщение с курсами среди прочих
# постов в канале (чтобы обычные объявления не ломали парсинг).
RATES_HASHTAG = "#курсы"

CURRENCY_NAMES = {
    "USD": "Доллар США",
    "EUR": "Евро",
    "USDT": "Tether",
    "GBP": "Фунт стерлингов",
    "CNY": "Юань",
    "RUB": "Рубль",
    "PLN": "Злотый",
    "KZT": "Тенге",
    "TRY": "Турецкая лира",
    "AED": "Дирхам ОАЭ",
}

LINE_RE = re.compile(
    r"^\s*([A-Za-zА-Яа-я]{2,5})\s+([0-9]+[.,][0-9]+)\s+([0-9]+[.,][0-9]+)\s*$"
)


def fetch_channel_html(channel: str) -> str:
    url = f"https://t.me/s/{channel}"
    headers = {
        # без реалистичного User-Agent Telegram иногда отдаёт урезанную страницу
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
            last_match = text  # t.me/s отдаёт сообщения от старых к новым,
            # поэтому последнее совпадение в цикле — самое свежее

    return last_match


def parse_rates(message_text: str) -> list[dict]:
    rates = []
    for raw_line in message_text.splitlines():
        m = LINE_RE.match(raw_line)
        if not m:
            continue
        code, buy_raw, sell_raw = m.groups()
        code = code.upper()
        buy = float(buy_raw.replace(",", "."))
        sell = float(sell_raw.replace(",", "."))
        rates.append(
            {
                "code": code,
                "name": CURRENCY_NAMES.get(code, code),
                "buy": buy,
                "sell": sell,
            }
        )
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
        return 0  # не считаем это фатальной ошибкой сборки

    rates = parse_rates(message_text)
    if not rates:
        print(
            "Сообщение с тегом найдено, но ни одна строка не распозналась "
            "как курс (проверьте формат 'USD 92.10 93.50').",
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
    print(f"Обновлено {len(rates)} курсов из канала @{channel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
