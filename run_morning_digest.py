#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Запускатель утренней рассылки для Windows Task Scheduler.

Загружает переменные из .env (в т.ч. Ollama-переменные для headless claude),
поднимает `claude -p` с промптом из prompt_digest.txt (stdin), логирует
результат в data/scheduler_log.txt. Сам дайджест делает Claude в headless —
здесь только спавн и лог.

Запуск (Task Scheduler):
  py -X utf8 D:\\Cabinet\\AI\\Claude\\project_news\\run_morning_digest.py
Smoke-тест (без отправки в TG, просто проверка headless claude):
  py -X utf8 run_morning_digest.py --smoke
"""
import argparse
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(ROOT, "prompt_digest.txt")
LOG_FILE = os.path.join(ROOT, "data", "scheduler_log.txt")

from send_digest import load_env  # noqa: E402  (переиспользуем загрузку .env)


def log(msg):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}Z] {msg}\n")


def tg_reachable(timeout=10):
    """Пре-чек: доступен ли api.telegram.org (без ВПН в РФ он не открывается).
    Сбой отправки из-за выключенного ВПН должен быть виден в логе сразу
    и с явной причиной, а не потеряться в stderr headless-прогона."""
    try:
        with urllib.request.urlopen("https://api.telegram.org", timeout=timeout) as r:
            return True, f"HTTP {r.status}"
    except Exception as e:
        return False, repr(e)


def collect_feedback():
    """Шаг 0: вычитывает оценки 👍/👎 от Юрия (накопились за сутки).
    Best-effort: сбой фидбека не должен ломать рассылку."""
    try:
        r = subprocess.run(
            [sys.executable, "-X", "utf8",
             os.path.join(ROOT, "collect_feedback.py")],
            cwd=ROOT, capture_output=True, timeout=120)
        out = r.stdout.decode("utf-8", "replace").strip()
        log(f"фидбек: exit={r.returncode} | {out[:200]}")
    except Exception as e:
        log(f"фидбек: ОШИБКА (не критично): {e!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="тест headless claude без рассылки")
    args = ap.parse_args()

    load_env()
    collect_feedback()
    ok, detail = tg_reachable()
    if ok:
        log("пре-чек: api.telegram.org доступен")
    else:
        log(f"ПРЕДУПРЕЖДЕНИЕ: api.telegram.org недоступен ({detail}) — "
            f"вероятно, ВПН выключен; рассылка не дойдёт")
    with open(PROMPT_FILE, encoding="utf-8") as f:
        prompt = f.read()
    if args.smoke:
        prompt = "Ответь ровно одним словом: OK (это smoke-тест headless, ничего не запускай)."
        log("smoke-тест: старт claude -p")
    else:
        log("запуск claude -p (промпт рассылки)")

    cmd = ["claude", "-p",
           "--allowedTools", "Bash Read Write Edit Glob Grep Agent",
           "--disallowedTools", "WebFetch WebSearch"]
    try:
        r = subprocess.run(cmd, input=prompt.encode("utf-8"), cwd=ROOT,
                           capture_output=True, timeout=30 * 60)
        out = r.stdout.decode("utf-8", "replace").strip()
        err = r.stderr.decode("utf-8", "replace").strip()
        log(f"exit={r.returncode} | stdout[:500]={out[:500]!r} | stderr[:300]={err[:300]!r}")
        print(f"exit={r.returncode}")
        print(out[:2000])
        if err:
            print(f"[stderr] {err[:1000]}")
        return r.returncode
    except Exception as e:
        log(f"ОШИБКА: {e!r}")
        print(f"ОШИБКА: {e!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())