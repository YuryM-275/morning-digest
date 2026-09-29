#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отправка готового дайджеста в Telegram-бота.

Читает TG_BOT_TOKEN и TG_CHAT_ID из .env, конвертирует markdown-дайджест
в Telegram HTML (жирные заголовки, кликабельные ссылки) и шлёт через sendMessage.
Дайджест ≤3000 символов — влезает в один сообщение ТГ (лимит 4096); при превышении
режется по строкам на несколько сообщений.

Запуск:
  py send_digest.py digest_2026-08-25.md            # отправить
  py send_digest.py digest_2026-08-25.md --dry-run  # показать HTML без отправки
"""
import os
import sys
import re
import json
import argparse
import urllib.request
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(ROOT, ".env")
DATA_DIR = os.path.join(ROOT, "data")
MARKER_FILE = os.path.join(DATA_DIR, "last_dispatch.txt")
SENT_MAP_FILE = os.path.join(DATA_DIR, "sent_digests.json")
TG_API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4000  # запас от лимита 4096


def shift_marker():
    """Сдвигает маркер «доставлено до Юрия» на текущий UTC после успешной
    отправки. Семантика маркера — момент доставки, а не момент сбора постов
    (сбор идёт с --no-mark, см. bot.py). Fallback-окно при следующем запуске
    отсчитывается от этой отметки."""
    import datetime
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MARKER_FILE, "w", encoding="utf-8") as f:
        f.write(datetime.datetime.now(datetime.timezone.utc).isoformat())


def record_sent(digest_file, results):
    """Сохраняет message_id отправленных сообщений → дата дайджеста.
    collect_feedback.py по этой карте понимает, на какой выпуск
    Юрий ответил 👍/👎 (реплаем или просто текстом)."""
    import datetime
    os.makedirs(DATA_DIR, exist_ok=True)
    mapping = {}
    if os.path.exists(SENT_MAP_FILE):
        try:
            with open(SENT_MAP_FILE, encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception:
            mapping = {}
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(digest_file))
    digest_date = m.group(1) if m else datetime.date.today().isoformat()
    for r in results:
        mid = (r.get("result") or {}).get("message_id")
        if mid:
            mapping[str(mid)] = digest_date
    # держим только последние 40 сообщений (маппинг не растёт бесконечно)
    items = sorted(mapping.items(), key=lambda kv: int(kv[0]))[-40:]
    with open(SENT_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(items), f, ensure_ascii=False, indent=1)
    return digest_date


def load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8"):
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    for k, v in env.items():
        os.environ.setdefault(k, v)
    return env


def esc(s):
    """Экранирование для Telegram HTML."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_to_html(md):
    """Простой конвертер формата нашего дайджеста в Telegram HTML."""
    out = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if re.match(r"^-{3,}\s*$", line):        # горизонтальная черта → пропуск
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)  # заголовки → жирный
        body = m.group(2) if m else line
        body = esc(body)
        # ссылки [text](url) на уже экранированном тексте
        body = re.sub(
            r"\[([^\]]+)\]\((https?://[^\)]+)\)",
            lambda mm: f'<a href="{mm.group(2)}">{mm.group(1)}</a>',
            body,
        )
        out.append(f"<b>{body}</b>" if m else body)
    return "\n".join(out)


def chunk(text, limit=MAX_LEN):
    """Режет HTML по строкам на куски ≤ limit (не разрывая строки)."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for ln in text.split("\n"):
        if len(cur) + len(ln) + 1 > limit:
            if cur:
                chunks.append(cur)
            cur = ln
        else:
            cur = (cur + "\n" + ln) if cur else ln
    if cur:
        chunks.append(cur)
    return chunks


def call_api(token, method, payload):
    url = TG_API.format(token=token, method=method)
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return {"ok": False, "error_code": e.code, "description": body}


def send(token, chat_id, html_text):
    chunks = chunk(html_text)
    results = []
    for i, c in enumerate(chunks, 1):
        payload = {
            "chat_id": chat_id,
            "text": c,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        if len(chunks) > 1:
            payload["text"] = f"(часть {i}/{len(chunks)})\n" + c
        r = call_api(token, "sendMessage", payload)
        results.append(r)
        if not r.get("ok"):
            break
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="файл дайджеста (.md)")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать HTML и длину без отправки")
    ap.add_argument("--chat-id", default=None,
                    help="переопределить chat_id из .env")
    ap.add_argument("--no-mark", action="store_true",
                    help="не сдвигать маркер last_dispatch.txt (для тестов)")
    args = ap.parse_args()

    env = load_env()
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = (args.chat_id or os.environ.get("TG_CHAT_ID", "")).strip()

    if not os.path.exists(args.file):
        print(f"Файл не найден: {args.file}")
        sys.exit(1)

    md = open(args.file, encoding="utf-8").read()
    html = md_to_html(md)
    print(f"HTML дайджест: {len(html)} символов, {len(chunk(html))} сообщ.\n")

    if args.dry_run:
        print("=== DRY-RUN: payload (без отправки) ===")
        print(html)
        if not token:
            print("\n[!] TG_BOT_TOKEN не задан в .env — отправка всё равно не состоялась бы.")
        if not chat_id:
            print("[!] TG_CHAT_ID не задан в .env.")
        return

    if not token or not chat_id:
        print("Нет токена/chat_id. Заполни .env (TG_BOT_TOKEN, TG_CHAT_ID) и повтори.")
        sys.exit(2)

    print(f"Отправляю в chat_id {chat_id} ...")
    results = send(token, chat_id, html)
    ok = all(r.get("ok") for r in results)
    for r in results:
        if r.get("ok"):
            print("  ✓ отправлено")
        else:
            print(f"  ✗ ошибка: {r.get('error_code')} {r.get('description','')[:200]}")
    if ok:
        digest_date = record_sent(args.file, results)
        if not args.no_mark:
            shift_marker()
            print(f"  ✓ маркер сдвинут; message_id записан за выпуск {digest_date}")
        else:
            print(f"  ✓ message_id записан за выпуск {digest_date} (маркер не тронут)")
    sys.exit(0 if ok else 3)


if __name__ == "__main__":
    main()