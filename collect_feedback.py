#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сбор оценки выпусков 👍/👎 от Юрия через getUpdates бота рассылки.

Юрий отвечает 👍/👎 на сообщение дайджеста (или просто шлёт эмодзи боту).
Этот скрипт одноразово вычитывает накопившиеся updates (offset-based,
каждое обновление обрабатывается ровно один раз) и дописывает их в
data/feedback.csv: ts_UTC, digest_date, rating, comment.

Сопоставление сообщения → выпуск:
  - реплай на сообщение дайджеста → по карте data/sent_digests.json
  - обычное сообщение (не реплай) → к последнему отправленному дайджесту
  - прочий текст (не 👍/👎) → игнор (но offset всё равно сдвигается)

Запуск:
  py -X utf8 collect_feedback.py          # одноразовый вычит
Проверка статистики:
  py -X utf8 collect_feedback.py --stats
"""
import os
import sys
import json
import csv
import argparse
import urllib.parse
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from send_digest import load_env, call_api  # переиспользование

DATA_DIR = os.path.join(ROOT, "data")
OFFSET_FILE = os.path.join(DATA_DIR, "feedback_offset.txt")
SENT_MAP_FILE = os.path.join(DATA_DIR, "sent_digests.json")
FEEDBACK_CSV = os.path.join(DATA_DIR, "feedback.csv")

THUMB_UP = "👍"
THUMB_DOWN = "👎"


def read_offset():
    try:
        with open(OFFSET_FILE, encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def write_offset(offset):
    with open(OFFSET_FILE, "w", encoding="utf-8") as f:
        f.write(str(offset))


def load_sent_map():
    try:
        with open(SENT_MAP_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def latest_digest_date(sent_map):
    if not sent_map:
        return None
    dates = sorted(sent_map.values())
    return dates[-1]


def parse_rating(text):
    """👍/👎 (со скин-модификаторами) в начале текста → (rating, comment)."""
    t = (text or "").strip()
    if not t:
        return None, ""
    if t.startswith(THUMB_UP):
        return "up", t[len(THUMB_UP):].strip()
    if t.startswith(THUMB_DOWN):
        return "down", t[len(THUMB_DOWN):].strip()
    return None, ""


def append_row(ts, digest_date, rating, comment):
    os.makedirs(DATA_DIR, exist_ok=True)
    new_file = not os.path.exists(FEEDBACK_CSV)
    with open(FEEDBACK_CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts_utc", "digest_date", "rating", "comment"])
        w.writerow([ts, digest_date, rating, comment])


def collect():
    load_env()
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    if not token:
        print("Нет TG_BOT_TOKEN в .env")
        return 2

    sent_map = load_sent_map()
    latest = latest_digest_date(sent_map)
    offset = read_offset()

    url = "https://api.telegram.org/bot{}/getUpdates".format(token)
    payload = {"offset": offset, "timeout": 0, "limit": 100}
    resp = call_api(token, "getUpdates", payload)
    if not resp.get("ok"):
        print("Ошибка getUpdates: {}".format(
            resp.get("description", "")[:200]))
        return 3

    updates = resp.get("result", [])
    processed, counted = 0, 0
    max_offset = offset
    for upd in updates:
        max_offset = max(max_offset, upd.get("update_id", 0) + 1)
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue
        processed += 1
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # дата дайджеста: реплай на сообщение из карты, иначе последний выпуск
        reply = msg.get("reply_to_message") or {}
        digest_date = sent_map.get(str(reply.get("message_id"))) or latest
        rating, comment = parse_rating(msg.get("text", ""))
        if not rating or not digest_date:
            continue  # посторонний текст — не оценка
        append_row(ts, digest_date, rating, comment)
        counted += 1
        emoji = "👍" if rating == "up" else "👎"
        print("{} выпуск {}: {}{}".format(ts, digest_date, emoji,
                                          (" — " + comment) if comment else ""))

    if max_offset != offset:
        write_offset(max_offset)
    print("Обработано сообщений: {} (из них оценок: {})".format(
        processed, counted))
    return 0


def stats():
    if not os.path.exists(FEEDBACK_CSV):
        print("Оценок пока нет ({} отсутствует)".format(FEEDBACK_CSV))
        return 0
    rows = list(csv.DictReader(open(FEEDBACK_CSV, encoding="utf-8")))
    up = sum(1 for r in rows if r["rating"] == "up")
    down = len(rows) - up
    print("Всего оценок: {} (👍 {}, 👎 {})".format(len(rows), up, down))
    by_date = {}
    for r in rows:
        by_date.setdefault(r["digest_date"], []).append(r["rating"])
    for d in sorted(by_date):
        ratings = by_date[d]
        score = sum(1 if x == "up" else -1 for x in ratings)
        print("  {}: {} (баланс {:+d})".format(d, "/".join(ratings), score))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true",
                    help="показать статистику оценок и выйти")
    args = ap.parse_args()
    sys.exit(stats() if args.stats else collect())


if __name__ == "__main__":
    main()