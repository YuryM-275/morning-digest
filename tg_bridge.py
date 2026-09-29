#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Поллинг-мост Telegram → headless Claude Code (провайдер Ollama).

Ловит входящие сообщения бота общения @YuryAssistantBot_bot (токен
TELEGRAM_BOT_TOKEN из .env) через long-poll getUpdates. На каждое сообщение
Юрия запускает headless `claude -p` (рабочая папка = этот проект), который
отвечает, вызвав MCP-инструмент tg_send_message (сервер tg_mcp_server.py,
зарегистрирован в .mcp.json). Если Claude не вызвал инструмент — fallback:
отправляет stdout ответа напрямую.

Каждая команда — отдельный headless-запрос (без контекста диалога).

Запуск (в отдельном терминале, VPN включён — api.telegram.org заблокирован):
  PYTHONIOENCODING=utf-8 py -X utf8 tg_bridge.py
Ctrl+C — выход.
"""
import os
import sys
import json
import time
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import urllib.request
import urllib.parse
import urllib.error

from send_digest import load_env, call_api  # переиспользование

DATA_DIR = os.path.join(ROOT, "data")
OFFSET_FILE = os.path.join(DATA_DIR, "tg_offset.txt")
MARKER_FILE = os.path.join(DATA_DIR, "tg_sent_marker.txt")
MCP_CONFIG = os.path.join(ROOT, ".mcp.json")  # абсолютный путь (важно для --mcp-config)
ALLOWED_TOOL = "mcp__telegram__tg_send_message"
CLAUDE_TIMEOUT = 300  # секунды на headless-ответ
POST_TIMEOUT = 600    # «сделай пост» — чтение дайджеста + JSON, дольше
SKILL_POST = os.path.join(ROOT, ".claude", "skills", "digest-to-post.md")
POST_MARKER = "сделай пост"  # команда от Юрия (без учёта регистра)

_env = load_env()
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
OWNER = os.environ.get("TG_CHAT_ID", "").strip()


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def read_offset():
    try:
        with open(OFFSET_FILE, encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except (OSError, ValueError):
        return 0


def write_offset(offset):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(OFFSET_FILE, "w", encoding="utf-8") as f:
            f.write(str(offset))
    except OSError:
        pass


def marker_size():
    try:
        return os.path.getsize(MARKER_FILE)
    except OSError:
        return 0


def send_plain(text):
    """Fallback-отправка plain text напрямую (без MCP), если Claude не вызвал инструмент."""
    if not TOKEN or not OWNER:
        log("  fallback: нет токена/chat_id — отправить не могу")
        return False
    r = call_api(TOKEN, "sendMessage", {
        "chat_id": OWNER,
        "text": text[:4000],
        "disable_web_page_preview": "true",
    })
    ok = r.get("ok")
    log(f"  fallback отправка: {'✓' if ok else '✗ ' + str(r.get('description',''))[:150]}")
    return ok


def run_claude(user_text):
    """Запускает headless claude -p с инструкцией ответить через tg_send_message.
    Возвращает True если ответ ушёл (через MCP или fallback), False если не вышло."""
    if POST_MARKER in user_text.lower():
        prompt = (
            "Тебе написал Юрий через Telegram-бота общения (владелец проекта). "
            f"Текст сообщения:\n«{user_text}»\n\n"
            "Это команда «сделай пост». Прочитай файл скилла\n"
            f"{SKILL_POST}\n"
            "и выполни его шаг за шагом: возьми последний digest_ГГГГ-ММ-ДД.md в "
            "корне рабочей папки (если Юрий указал тему — пункт той темы), создай "
            "JSON-черновик поста в posts/ строго по формату скилла. Факты только из "
            "дайджеста. Потом отправь ответ Юрию через инструмент tg_send_message: "
            "заголовок поста, имя созданного файла и ПОЛНЫЙ текст Telegram-версии "
            "(он же черновик — Юрий его скопирует). Не отправляй ничего кроме этого "
            "ответа. Не читай/не записывай .env."
        )
        allowed = "Read Write Glob Grep Edit " + ALLOWED_TOOL
        timeout = POST_TIMEOUT
    else:
        prompt = (
            "Тебе написал Юрий через Telegram-бота общения. Это его личное сообщение "
            "тебе (владельцу проекта). Текст сообщения:\n"
            f"«{user_text}»\n\n"
            "Ответь Юрию кратко по-русски. ОБЯЗАТЕЛЬНО отправь ответ, вызвав инструмент "
            "tg_send_message с текстом ответа. Не ограничивайся текстом в чате — Юрий "
            "получит ответ только через tg_send_message."
        )
        allowed = ALLOWED_TOOL
        timeout = CLAUDE_TIMEOUT
    before = marker_size()
    cmd = [
        "claude", "-p",
        "--mcp-config", MCP_CONFIG,
        "--strict-mcp-config",
        "--allowedTools", allowed,
    ]
    log(f"  запуск claude -p (timeout {timeout}s)…")
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=ROOT,
        )
    except subprocess.TimeoutExpired:
        log("  ✗ claude превысил timeout")
        send_plain("⏱ Claude думал слишком долго — попробуй переформулировать.")
        return False
    except FileNotFoundError:
        log("  ✗ команда `claude` не найдена в PATH")
        send_plain("⚠ Не нашёл CLI `claude` — проверь установку/PATH.")
        return False

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    after = marker_size()

    if after > before:
        log("  ✓ ответ отправлен через MCP (tg_send_message)")
        if err:
            log(f"  (stderr: {err[:200]})")
        return True

    # Claude не вызвал инструмент — fallback на stdout
    log("  MCP-инструмент не вызван → fallback на stdout")
    if err:
        log(f"  (stderr: {err[:200]})")
    if out:
        return send_plain(out)
    log("  ✗ stdout пуст — ответить нечем")
    send_plain("⚠ Claude не сформировал ответ. Попробуй ещё раз.")
    return False


def handle_message(msg):
    chat = msg.get("chat", {})
    chat_id = str(chat.get("id", ""))
    chat_type = chat.get("type", "")
    text = msg.get("text", "")

    if chat_type != "private":
        log(f"  пропуск: не приватный чат ({chat_type})")
        return
    if OWNER and chat_id != OWNER:
        log(f"  [отклонено] чужой chat_id={chat_id}")
        return
    if not text:
        log("  пропуск: нет text (стикер/медиа/команда) — MVP работает только с текстом")
        return

    sender = chat.get("first_name", "") or chat.get("username", "") or "?"
    log(f"← {sender} (chat {chat_id}): {text[:80]}")
    run_claude(text)


def poll_loop():
    if not TOKEN:
        log("✗ TELEGRAM_BOT_TOKEN не задан в .env — выхожу")
        sys.exit(1)
    if not OWNER:
        log("✗ TG_CHAT_ID не задан в .env — выхожу")
        sys.exit(1)
    log(f"Бот общения запущен. Владелец chat_id={OWNER}. Ctrl+C — выход.")
    log("Жду сообщения @YuryAssistantBot_bot (long-poll, VPN должен быть включён)…")

    offset = read_offset()
    while True:
        payload = {
            "offset": offset,
            "timeout": 25,
            "allowed_updates": ["message"],
        }
        try:
            r = call_api(TOKEN, "getUpdates", payload)
        except Exception as e:
            log(f"  сеть ошибка getUpdates: {e}; жду 10s")
            time.sleep(10)
            continue

        if not r.get("ok"):
            code = r.get("error_code")
            desc = r.get("description", "")
            if code == 409:
                log("  409 Conflict — другой процесс polling этот токен "
                    "(плагин telegram?). жду 15s")
            else:
                log(f"  getUpdates ошибся: {code} {desc[:150]}; жду 10s")
            time.sleep(15 if code == 409 else 10)
            continue

        updates = r.get("result", []) or []
        for upd in updates:
            uid = upd.get("update_id")
            if uid is not None:
                offset = uid + 1
            msg = upd.get("message")
            if msg:
                handle_message(msg)
        if updates:
            write_offset(offset)


if __name__ == "__main__":
    try:
        poll_loop()
    except KeyboardInterrupt:
        log("Останавливаюсь…")
        write_offset(read_offset())