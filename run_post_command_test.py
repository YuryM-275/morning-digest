#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Живой тест ветки «сделай пост»: дёргает tg_bridge.run_claude как в бою.

Запуск: py -X utf8 run_post_command_test.py
Ответ придёт Юрию в бота ассистента (через MCP tg_send_message).
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import tg_bridge

ok = tg_bridge.run_claude("сделай пост")
print("RESULT:", "✓ ответ ушёл" if ok else "✗ ответ не ушёл")
sys.exit(0 if ok else 1)