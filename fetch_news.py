#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Обёртка: забирает все каналы из channels.txt, парсит, дедуплицирует,
классифицирует по темам и сохраняет:
  - data/posts_ГГГГ-ММ-ДД.json   — структура для ИИ-пересказа
  - digest_raw_ГГГГ-ММ-ДД.md     — черновик дайджеста по темам (полный текст)

Полированный дайджест с пересказом сути делает ИИ в сессии из JSON.

Запуск:
  py fetch_news.py [--hours 24] [--limit 25] [--maxlen 800]
"""
import sys
import os
import re
import json
import argparse
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from parse_tg import parse_file, clean  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
CHANNELS_FILE = os.path.join(ROOT, "channels.txt")
DATA_DIR = os.path.join(ROOT, "data")
MARKER_FILE = os.path.join(DATA_DIR, "last_dispatch.txt")  # UTC ISO последнего выпуска

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# Темы итогового дайджеста (по запросу Юрия). Крипта сливаются в «Инвестиции».
THEMES = [
    ("Энергетика", ["нефть", "газ ", "газа", "россети", "квт", "гвт", "мвт",
                    "электроэн", "лэп", "аэс", "реактор", "тепл", "энергобаланс",
                    "нпз", "гхк", "росатом", "генераци", "виэ", "солнечн",
                    "ветр", "уголь", "нефтеперераб", "ктк", "тэр", "квт·",
                    "энергосбыт", "орэм", "лэп"]),
    ("Инвестиции и рынки", ["индекс", "мосбирж", "imoex", "re:\\bакци", "дивиденд", "облигац",
                            "выручк", "прибыл", "эмитент", "портфел", "s&p", "nasdaq",
                            "бирж", "котиров", "бумаг", "золото", "унция", "капитализац",
                            "крипт", "биткоин", "btc", "ethereum", "эфир", "eth ",
                            "токен", "стейкинг", "стейблкоин", "usdt", "usdc", "defi",
                            "nft", "блокчейн", "солана", "etf ", "стейбл"]),
    ("Экономика", ["рубл", "валют", "курс ", "ввп", "рецесс", "инфляц",
                   "ставка цб", "ключевая ставка", "юань", "cnyrub",
                   "доллар", "экспорт", "экономик", "макро", "госзакуп"]),
    ("Технологии", ["нейросет", " ии ", "ai ", "квант", "робот", "чип",
                    "nvidia", "hugging", "spacexai", "llm", "модель ",
                    "дата-центр", "кубит", "spacex", "мкс", "космос", "марс"]),
    ("Общество", ["рождаем", "демограф", "туризм", "автосервис", "кофеин",
                  "маркетплейс", "гостиниц", "отель"]),
    ("Культура", ["концерт", "кань", "билет", "кино", "сериал", "музык",
                  "театр", "выставк", "кион", "dota"]),
    ("Спорт", ["футбол", "хоккей", "баскетбол", "теннис", "матч", "турнир",
               "олимп", "бокс", "гонк", "шахмат", "киберспорт", "the international"]),
]

# Стоп-слова: меньше политики, происшествий, конфликтов. Пост помечается, но в JSON
# сохраняется весь — финальную отбраковку делает ИИ при сборке дайджеста.
STOP_WORDS = [
    "мобилиз", "бпла", "беспилотник", "атак на", "атаки на", "удар по", "пожар",
    "возгорание", "внуково", "ввс сша", "кочарян", "песков", "лавров", "ватикан",
    "днр", "военные взяли", "происшеств", "дтп", "погиб", "пострадал", "задержан",
    "арест", "украин", "всу",
]

THEME_EMOJI = {
    "Энергетика": "⚡️",
    "Инвестиции и рынки": "📈",
    "Экономика": "💰",
    "Технологии": "🤖",
    "Общество": "🌐",
    "Культура": "🎭",
    "Спорт": "🏅",
}
THEME_ORDER = list(THEME_EMOJI.keys())


def load_channels():
    out = []
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(s)
    return out


def fetch_channel(name, timeout=25):
    """Скачивает HTML t.me/s/<name> во временный файл, возвращает путь."""
    fd, path = tempfile.mkstemp(suffix=".html", prefix=f"tg_{name}_")
    os.close(fd)
    url = f"https://t.me/s/{name}"
    try:
        subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), "-A", UA,
             url, "-o", path],
            check=False, timeout=timeout + 5,
        )
        return path
    except Exception:
        return path  # вернём пустой/неполный, parse_file это переживёт


def fetch_rss(url, timeout=25):
    """Скачивает RSS-ленту и возвращает посты в формате parse_file:
    [{"time": "...", "link": "...", "text": "..."}, ...]
    """
    fd, path = tempfile.mkstemp(suffix=".xml", prefix="rss_")
    os.close(fd)
    try:
        subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), "-A", UA,
             url, "-o", path],
            check=False, timeout=timeout + 5,
        )
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
    except Exception:
        data = ""
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    posts = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return posts
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        # description часто дублирует title или содержит HTML — берём, если что-то новое
        text = title
        if desc and normalize(desc) != normalize(title):
            d = re.sub(r"<[^>]+>", " ", desc)  # срезать HTML-теги
            text = f"{title}. {d.strip()}"
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        try:
            t = parsedate_to_datetime(pub)
        except Exception:
            continue
        if not text:
            continue
        posts.append({
            "time": t.strftime("%Y-%m-%d %H:%M UTC"),
            "link": link,
            "text": clean(text),
        })
    return posts


def normalize(text):
    return re.sub(r"\s+", " ", text.lower()).strip()


def is_stopped(text):
    """True, если пост — политика/происшествие/конфликт (по стоп-словам)."""
    norm = " " + normalize(text) + " "
    return any(sw in norm for sw in STOP_WORDS)


def classify(text):
    norm = " " + normalize(text) + " "
    best, best_score = None, 0
    for theme, kws in THEMES:
        score = 0
        for kw in kws:
            if kw.startswith("re:"):  # regex-ключ (ловушки вида «вакцинация»/«акции»)
                hit = re.search(kw[3:], norm)
            else:
                hit = kw in norm
            score += 1 if hit else 0
        if score > best_score:
            best, best_score = theme, score
    return best  # None → пост не попал ни в одну тему, в дайджест не идёт


def read_marker():
    """Возвращает datetime последнего выпуска (UTC) или None."""
    if not os.path.exists(MARKER_FILE):
        return None
    try:
        s = open(MARKER_FILE, "r", encoding="utf-8").read().strip()
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def write_marker(dt):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MARKER_FILE, "w", encoding="utf-8") as f:
        f.write(dt.astimezone(timezone.utc).isoformat())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24,
                    help="запасное окно, если маркера нет (по умолч. 24)")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--maxlen", type=int, default=800)
    ap.add_argument("--since", type=str, default=None,
                    help="явный cutoff ISO; перекрывает маркер")
    ap.add_argument("--max-hours", type=int, default=None,
                    help="максимум окна (ч): если маркер старше, cutoff режется до now-max-hours")
    ap.add_argument("--no-mark", action="store_true",
                    help="не обновлять маркер после выпуска (предпросмотр)")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    channels = load_channels()
    today = datetime.now().strftime("%Y-%m-%d")

    run_now = datetime.now(timezone.utc)
    # cutoff: --since > маркер > now-hours
    if args.since:
        cutoff = datetime.fromisoformat(args.since)
        cutoff = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
        src = "--since"
    else:
        m = read_marker()
        if m is not None:
            cutoff, src = m, "маркер"
        else:
            cutoff, src = run_now - timedelta(hours=args.hours), f"fallback {args.hours}ч"
    # Ограничение окна: пропуски не копим, обзор только за последние N часов
    if args.max_hours is not None and (run_now - cutoff).total_seconds() / 3600 > args.max_hours:
        cutoff = run_now - timedelta(hours=args.max_hours)
        src += f"→обрезано до {args.max_hours}ч"
    window_h = (run_now - cutoff).total_seconds() / 3600
    print(f"Каналов: {len(channels)} | окно с {cutoff.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
          f"({window_h:.1f}ч, {src}) | дата: {today}\n")

    all_posts = []  # {channel, time, link, text, theme, stopped}
    seen = {}       # нормализованный префикс -> индекс в all_posts
    dups = 0
    n_stopped = 0   # помечены стоп-словами
    n_notheme = 0   # не попали ни в одну тему
    per_channel = {}

    for ch in channels:
        # rss:<URL>|<имя> → имя подставляется в дайджест вместо длинного URL
        rss_url = rss_name = None
        if ch.startswith("rss:"):
            body = ch[4:]
            if "|" in body:
                rss_url, rss_name = body.split("|", 1)
            else:
                rss_url = body
        if rss_url:
            posts = [p for p in fetch_rss(rss_url) if datetime.strptime(p["time"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc) >= cutoff]
            posts.sort(key=lambda x: x["time"], reverse=True)
            posts = posts[:args.limit]
            size = -1
        else:
            path = fetch_channel(ch)
            size = os.path.getsize(path) if os.path.exists(path) else 0
            posts = parse_file(path, hours=args.hours, limit=args.limit, since=cutoff) if size else []
            try:
                os.remove(path)
            except OSError:
                pass
        display = rss_name or ch
        per_channel[display] = len(posts)
        src_note = "rss" if size == -1 else f"html {size} байт"
        print(f"  {display:40s} — постов: {len(posts)} ({src_note})")
        for p in posts:
            key = normalize(p["text"])[:120]
            if not key:
                continue
            if key in seen:
                dups += 1
                continue
            stopped = is_stopped(p["text"])
            theme = classify(p["text"])
            if stopped:
                n_stopped += 1
            elif theme is None:
                n_notheme += 1
            seen[key] = len(all_posts)
            all_posts.append({
                "channel": display,
                "time": p["time"],
                "link": p["link"],
                "text": p["text"],
                "theme": theme,        # None, если тема не определена
                "stopped": stopped,    # True — политика/происшествие/конфликт
            })

    # Сохраняем JSON (полный текст, для ИИ-пересказа)
    json_path = os.path.join(DATA_DIR, f"posts_{today}.json")
    meta = {
        "date": today,
        "since": cutoff.astimezone(timezone.utc).isoformat(),
        "until": run_now.isoformat(),
        "window_hours": round((run_now - cutoff).total_seconds() / 3600, 2),
        "marker_source": src,
        "posts": all_posts,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Черновик Markdown по темам (только «чистые» посты — без стоп-слов и с темой)
    md_path = os.path.join(ROOT, f"digest_raw_{today}.md")
    by_theme = {t: [] for t in THEME_ORDER}
    for p in all_posts:
        if p["stopped"] or p["theme"] is None:
            continue
        by_theme[p["theme"]].append(p)

    n_digest = sum(len(v) for v in by_theme.values())
    lines = [f"# 🗞 Черновой дайджест — {today} (окно {window_h:.1f}ч с {src}, raw)\n",
             f"Всего постов: {len(all_posts)} | в дайджест: {n_digest} | "
             f"дубликатов удалено: {dups} | стоп: {n_stopped} | без темы: {n_notheme}\n"]
    for theme in THEME_ORDER:
        items = by_theme[theme]
        if not items:
            continue
        emoji = THEME_EMOJI[theme]
        lines.append(f"\n## {emoji} {theme}\n")
        for p in items:
            txt = p["text"][:args.maxlen] + ("…" if len(p["text"]) > args.maxlen else "")
            lines.append(f"**[{p['channel']}]** {p['time']}")
            lines.append(f"🔗 {p['link']}")
            lines.append(f"{txt}\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # Маркер последнего выпуска (сдвигаем, чтобы следующий выпуск шёл с этого момента)
    if args.no_mark:
        mark_note = "маркер НЕ обновлён (--no-mark)"
    else:
        write_marker(run_now)
        mark_note = f"маркер → {run_now.isoformat()[:19]} UTC"

    print(f"\nГотово.")
    print(f"  JSON : {json_path}")
    print(f"  RAW  : {md_path}")
    print(f"  Постов: {len(all_posts)} (в дайджест {n_digest}), дублей: {dups}, стоп: {n_stopped}, без темы: {n_notheme}")
    print(f"  {mark_note}")


if __name__ == "__main__":
    main()