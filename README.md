# PingMe — Telegram Reminder Bot

Telegram-бот для создания напоминаний на естественном языке. Просто напиши что и когда — бот напомнит.

## Возможности

- Парсинг напоминаний из произвольного текста — без ключевых слов
- Поддержка русских форматов: `17.02`, `завтра`, `в пятницу`, `7 утра`, `13 часов`
- Запрос времени если указана только дата
- Список и удаление напоминаний
- REST API (FastAPI)
- PostgreSQL + Docker для продакшна

## Формат создания напоминания

```
текст дата время
```

Примеры:
```
позвонить маме завтра в 10:00
подъем 17.02 в 5 утра
встреча в пятницу в 15:00
написать заявление 20.02 в 13:40
выпить таблетку через 30 минут
напомни про стрижку завтра в 13 часов
```

Если время не указано — бот спросит отдельно.

## Команды

| Команда | Описание |
|---|---|
| `/list` | Список активных напоминаний |
| `/delete <ID>` | Удалить напоминание |
| `/help` | Справка |
| `/cancel` | Отменить текущее действие |

## Запуск через Docker (рекомендуется)

```bash
# Скопировать шаблон переменных
cp .env.example .env

# Вставить BOT_TOKEN в .env
# BOT_TOKEN=your_token_here

# Запустить
docker compose up --build -d
```

Бот и PostgreSQL поднимутся автоматически. Данные хранятся в Docker volume `postgres_data` и переживают перезапуски.

## Переменные окружения

| Переменная | Описание | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | Токен Telegram-бота | — |
| `DATABASE_URL` | URL базы данных | `postgresql+asyncpg://...` |
| `POSTGRES_USER` | Пользователь PostgreSQL | `pingme` |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL | `pingme` |
| `POSTGRES_DB` | Имя базы данных | `pingme` |
| `API_HOST` | Хост FastAPI | `0.0.0.0` |
| `API_PORT` | Порт FastAPI | `8000` |
| `TIMEZONE` | Временная зона | `Europe/Moscow` |
| `DEBUG` | Режим отладки | `false` |

## API

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/` | Health check |
| `GET` | `/api/v1/reminders` | Список напоминаний |
| `POST` | `/api/v1/reminders` | Создать напоминание |
| `DELETE` | `/api/v1/reminders/{id}` | Удалить напоминание |

## Тесты

```bash
docker compose exec bot pytest tests/ -v
```

## Структура проекта

```
pingme/
├── app/
│   ├── bot/
│   │   └── handlers/
│   │       ├── basic.py       # /start, /help
│   │       ├── reminders.py   # парсинг и создание напоминаний
│   │       └── fallback.py    # неизвестные команды и текст
│   ├── api/                   # FastAPI endpoints
│   ├── database/              # модели и подключение
│   ├── services/
│   │   └── scheduler.py       # APScheduler
│   └── config.py              # pydantic-settings
├── tests/
│   └── test_reminder_parser.py
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── main.py
```

## Бэкапы БД

```bash
# Создать дамп
docker compose exec postgres pg_dump -U pingme pingme > backup.sql

# Восстановить
docker compose exec -T postgres psql -U pingme pingme < backup.sql
```

## Стек

- **Python 3.11**
- **aiogram 3.x** — Telegram Bot API
- **FastAPI + uvicorn** — REST API
- **SQLAlchemy 2.x async + asyncpg** — ORM + PostgreSQL
- **APScheduler** — планировщик напоминаний
- **dateparser** — парсинг дат на русском языке
- **Docker + PostgreSQL 16**