---
name: repo-guide
description: Скилл работы с репозиторием morning-digest («Утренняя газета»). Использовать, когда Claude Code работает над этим проектом: разобраться в структуре, запустить пайплайн, внести изменения в темы/каналы/субагента, обновить README, проверить ошибки и подготовить к публикации.
---

# Repo Guide: morning-digest

Скилл для работы Claude Code с этим репозиторием. Проект — «Утренняя газета»:
пайплайн раз в день собирает посты Telegram-каналов, отбирает главное субагентом,
редактирует в дайджест ≤3000 символов и отправляет владельцу в Telegram.

## Карта репозитория

```
run_morning_digest.py   # оркестратор: один выпуск (пре-чек → сбор → отбор → отправка)
fetch_news.py           # выгрузка постов каналов через Telegram Bot API (urllib, без deps)
parse_tg.py             # парсинг ответов Telegram API → data/posts_*.json
send_digest.py          # markdown → Telegram HTML → отправка ботом в чат владельца
collect_feedback.py     # вычитка 👍/👎 из бота → data/feedback.csv
tg_bridge.py            # мост: Telegram ↔ headless Claude (команда «сделай пост»)
tg_mcp_server.py        # MCP-сервер: отправка ассистенту сообщений ботом
prompt_digest.txt       # промпт утреннего прогона: темы, стиль, стоп-фильтры
.claude/agents/digest-analyst.md    # субагент-редактор: отбор фактов по 7 темам
.claude/skills/digest-to-post.md    # скилл: дайджест → JSON-черновик поста
.claude/skills/ai-news-to-social.md # скилл: новость → пост в соцсеть
screenshots/            # скриншоты работающего проекта для README
channels.example.txt    # образец списка каналов (реальный channels.txt не в git)
.env.example            # образец секретов (реальный .env не в git)
```

## Как запустить

Секреты и список каналов положить рядом (см. `.env.example` и `channels.example.txt`):

```bash
cp .env.example .env     # вписать TG_BOT_TOKEN / TELEGRAM_BOT_TOKEN / TG_CHAT_ID
cp channels.example.txt channels.txt
py -m pip install -r requirements.txt   # только для tg_mcp_server.py
py -X utf8 run_morning_digest.py        # ручной выпуск
py -X utf8 tg_mcp_server.py             # MCP-сервер (по желанию)
```

Один и тот же бот может обслуживать и рассылку, и мост. Автозапуск —
задачи Windows Task Scheduler: `ClaudeMorningDigest` (07:58 ежедневно)
и `ClaudeTGBridge` (при входе в Windows, через `run_tg_bridge_hidden.ps1`).

## Как вносить изменения

- **Каналы** — по одному в строке `channels.txt`.
- **Темы, стиль, стоп-фильтры** — `prompt_digest.txt` и субагент `.claude/agents/digest-analyst.md`.
- **Окно сбора, время запуска, конвертация** — `run_morning_digest.py`.
- **Формат сообщений** — `send_digest.py` (лимит 3000 симв., markdown → HTML).
- Черновики постов и скиллы постинга не меняют отправку: они только готовят текст.

## Как проверить ошибки

```bash
py -X utf8 run_morning_digest.py        # вывод сразу в консоль
py -m py_compile *.py                   # проверка синтаксиса без запуска
```

- Логи прогонов: `data/scheduler_log.txt`, логи моста: `data/bridge_log.txt`.
- Telegram API недоступен (VPN/сеть) — пре-чек пишет отказ в лог и пайплайн останавливается сам, падения быть не должно.
- Отладочные файлы (`dbg.txt`, `out.txt`, `err.txt`) — мусор от прошлых прогонов, в git не брать.

## Как обновлять README

Появилась новая работающая функция → перечислить её в списке MVP с галочкой ✅,
поставить в `screenshots/` скриншот с датой в имени (`ГГГГ-ММ-ДД_что-показано_screenshot.png`),
если нужно — обновить схему «Что происходит» в разделе «Основная функция».
Планы не переносить в MVP, пока не подтверждены скриншотом или логом.

## Как готовить к публикации

- Секреты только в `.env` — `.gitignore` уже закрывает его, проверять `git status` перед коммитом.
- Рабочие данные (`data/`, `channels.txt`, дайджесты, посты) в git не попадают.
- В коммит — только файлы фичи, без служебного мусора.
- Коммиты: короткое имя фичи на английском, при необходимости — 3–5 строк деталей.
- Скриншоты персональных чатов блурить или переснимать на демонстрационных данных.