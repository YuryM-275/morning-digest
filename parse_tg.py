#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Парсер публичной ленты Telegram-канала (t.me/s/<name>).
Стандартная библиотека only (без bs4).
Извлекает посты: дата, ссылка, текст. Фильтрует за последние N часов.
"""
import sys
import re
import argparse
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser


class TgParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.posts = []          # список словарей
        self._cur = None         # текущий пост
        self._depth = 0          # глубина внутри message_wrap
        self._in_wrap = False
        self._capture_text = False
        self._text_buf = []
        self._in_date = False
        self._date_link = None
        self._datetime_attr = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")

        if "tgme_widget_message_wrap" in cls and not self._in_wrap:
            self._in_wrap = True
            self._cur = {"text": "", "link": None, "datetime": None}
            return

        if not self._in_wrap:
            return

        if "tgme_widget_message_text" in cls:
            self._capture_text = True
            self._text_buf = []
            return

        if tag == "a" and "tgme_widget_message_date" in cls:
            self._in_date = True
            self._date_link = a.get("href")
            return

        if tag == "time" and self._in_date:
            self._datetime_attr = a.get("datetime")

    def handle_endtag(self, tag):
        if not self._in_wrap:
            return

        if self._capture_text and tag == "div":
            self._capture_text = False
            self._cur["text"] = "".join(self._text_buf).strip()
            self._text_buf = []

        if self._in_date and tag == "a":
            self._in_date = False
            self._cur["link"] = self._date_link
            self._cur["datetime"] = self._datetime_attr

        if tag == "div":
            # закрываем message_wrap когда закрывается внешний div
            # эвристика: wrap — это div, содержащий text и date
            if self._cur and self._cur.get("text") and self._cur.get("link"):
                self.posts.append(self._cur)
                self._cur = None
                self._in_wrap = False

    def handle_data(self, data):
        if self._capture_text:
            self._text_buf.append(data)


def clean(text: str) -> str:
    # убрать лишние пробелы/переносы
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_file(path: str, hours: int = 24, limit: int = 50, since=None):
    """Извлекает посты не старее cutoff.
    since: datetime (с таймзоной) — нижняя граница. Если None — now - hours.
    """
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    p = TgParser()
    p.feed(html)

    now = datetime.now(timezone.utc)
    if since is not None:
        cutoff = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    else:
        cutoff = now - timedelta(hours=hours)
    out = []
    for post in p.posts:
        dt = post.get("datetime")
        if not dt:
            continue
        try:
            t = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            continue
        if t < cutoff:
            continue
        txt = clean(post["text"])
        if not txt:
            continue
        out.append({
            "time": t.strftime("%Y-%m-%d %H:%M UTC"),
            "link": post["link"],
            "text": txt,
        })
    out.sort(key=lambda x: x["time"], reverse=True)
    return out[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--maxlen", type=int, default=600)
    args = ap.parse_args()
    posts = parse_file(args.file, args.hours, args.limit)
    print(f"# Найдено постов за {args.hours}ч: {len(posts)}\n")
    for i, p in enumerate(posts, 1):
        txt = p["text"][:args.maxlen] + ("…" if len(p["text"]) > args.maxlen else "")
        print(f"## {i}. {p['time']}")
        print(f"🔗 {p['link']}")
        print(f"{txt}\n")


if __name__ == "__main__":
    main()