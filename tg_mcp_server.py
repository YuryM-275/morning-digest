#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP-сервер Telegram для бота общения.

Инструмент tg_send_message(text) — отправляет текст Юрию в Telegram через
бота @YuryAssistantBot_bot (токен TELEGRAM_BOT_TOKEN из .env). Используется
headless-сессией Claude (claude -p), запускаемой поллинг-мостом tg_bridge.py.

Это обычный MCP-сервер с инструментами (НЕ channel-плагин) — не требует
claude.ai OAuth, работает под провайдером Ollama.

Переиспользует низкоуровневые helpers из send_digest.py (call_api, load_env,
chunk, TG_API) — stdlib-only + mcp SDK v2.
"""
import os
import sys
import datetime

# Гарантируем что рабочая папка (с send_digest.py) в пути импорта
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mcp.server.mcpserver import MCPServer
from send_digest import load_env, call_api, chunk  # переиспользование

DATA_DIR = os.path.join(ROOT, "data")
MARKER_FILE = os.path.join(DATA_DIR, "tg_sent_marker.txt")


def _mark_sent():
    """Фиксирует факт успешной отправки в marker-файл (append timestamp).
    Поллинг-мост tg_bridge.py использует это чтобы отличить отправку через
    MCP-инструмент (Claude сам ответил) от случая, когда нужен fallback на stdout."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(MARKER_FILE, "a", encoding="utf-8") as f:
            f.write(datetime.datetime.now(datetime.timezone.utc).isoformat() + "\n")
    except OSError:
        pass  # marker — вспомогательный, не валить отправку из-за него

# Имя MCP-сервера = имя в .mcp.json; инструмент = mcp__telegram__tg_send_message
mcp = MCPServer("telegram")

# Загрузим .env один раз при старте сервера
_env = load_env()
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
OWNER_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()
MAX_LEN = 4000  # запас от лимита Telegram 4096


@mcp.tool()
def tg_send_message(text: str, chat_id: str = "") -> str:
    """Отправить текстовое сообщение Юрию в Telegram.

    Args:
        text: текст сообщения (plain text, будет нарезан на части ≤4000 символов).
        chat_id: необязательный chat_id; по умолчанию — владелец (Юрий).
            В целях безопасности принимается только chat_id владельца; иной
            chat_id отклоняется (защита от промпт-инъекций «отправь другому»).

    Returns:
        Строка-статус: 'отправлено: N сообщ.' или описание ошибки.
    """
    if not TOKEN:
        return "ошибка: TELEGRAM_BOT_TOKEN не задан в .env"
    target = (chat_id or OWNER_CHAT_ID).strip()
    if not target:
        return "ошибка: chat_id не задан и TG_CHAT_ID пуст в .env"
    if OWNER_CHAT_ID and target != OWNER_CHAT_ID:
        # Защита: отправка только владельцу
        return "отклонено: отправка разрешена только владельцу (TG_CHAT_ID)"

    if not text:
        return "ошибка: пустой text"

    parts = chunk(text, limit=MAX_LEN)
    sent = 0
    last_err = ""
    for i, part in enumerate(parts, 1):
        payload = {
            "chat_id": target,
            "text": part,
            "disable_web_page_preview": "true",
        }
        if len(parts) > 1:
            payload["text"] = f"(часть {i}/{len(parts)})\n" + part
        r = call_api(TOKEN, "sendMessage", payload)
        if r.get("ok"):
            sent += 1
        else:
            last_err = f"{r.get('error_code')} {r.get('description', '')[:200]}"
            break

    if sent == 0:
        return f"ошибка отправки: {last_err}"
    if sent < len(parts):
        _mark_sent()
        return f"частично: отправлено {sent}/{len(parts)}; последняя ошибка: {last_err}"
    _mark_sent()
    return f"отправлено: {sent} сообщ."


if __name__ == "__main__":
    mcp.run(transport="stdio")