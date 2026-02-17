# PingMe — Telegram Reminder Bot

Telegram-бот для создания напоминаний на естественном языке. Просто напиши что и когда — бот напомнит.

## Возможности

- Парсинг напоминаний из произвольного текста — без ключевых слов
- Поддержка русских форматов: `17.02`, `завтра`, `в пятницу`, `7 утра`, `13 часов`
- Запрос времени если указана только дата
- Inline-кнопки **Выполнено / Отложить на 1ч** при получении напоминания
- Автоповтор каждые 15 минут пока пользователь не подтвердит
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

## Поведение напоминания

Когда наступает время напоминания, бот отправляет сообщение с двумя кнопками:

```
[ ✅ Выполнено ]  [ ⏱ Отложить на 1ч ]
```

- **Выполнено** — напоминание закрывается, кнопки исчезают.
- **Отложить на 1ч** — напоминание переносится на +1 час, кнопки исчезают.
- Если кнопка не нажата — напоминание повторяется **каждые 15 минут** до подтверждения.

## Команды

| Команда        | Описание                       |
|----------------|--------------------------------|
| `/list`        | Список активных напоминаний    |
| `/delete <ID>` | Удалить напоминание            |
| `/help`        | Справка                        |
| `/cancel`      | Отменить текущее действие      |

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

## Деплой на сервер

Первый деплой:

```bash
git clone <repo> && cd pingme
cp .env.example .env
# Заполнить .env
docker compose up -d
```

Обновление (повторный деплой):

```bash
cd PingMe
./deploy.sh
```

Скрипт автоматически:
1. Делает бэкап БД в `backups/`
2. Выполняет `git pull`
3. Пересобирает образ бота
4. Перезапускает контейнер (миграции накатываются автоматически)

Логи после деплоя:

```bash
docker compose logs -f bot
```

## Переменные окружения

| Переменная          | Описание                   | По умолчанию              |
|---------------------|----------------------------|---------------------------|
| `BOT_TOKEN`         | Токен Telegram-бота        | —                         |
| `DATABASE_URL`      | URL базы данных            | `postgresql+asyncpg://...`|
| `POSTGRES_USER`     | Пользователь PostgreSQL    | `pingme`                  |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL          | `pingme`                  |
| `POSTGRES_DB`       | Имя базы данных            | `pingme`                  |
| `API_HOST`          | Хост FastAPI               | `0.0.0.0`                 |
| `API_PORT`          | Порт FastAPI               | `8000`                    |
| `TIMEZONE`          | Временная зона             | `Europe/Moscow`           |
| `DEBUG`             | Режим отладки              | `false`                   |

## API

| Метод    | Путь                       | Описание               |
|----------|----------------------------|------------------------|
| `GET`    | `/`                        | Health check           |
| `GET`    | `/api/v1/reminders`        | Список напоминаний     |
| `POST`   | `/api/v1/reminders`        | Создать напоминание    |
| `DELETE` | `/api/v1/reminders/{id}`   | Удалить напоминание    |

## Разработка

Установка dev-зависимостей:

```bash
pip install -r requirements-dev.txt
```

## Тесты

```bash
docker compose exec bot pytest tests/ -v
```

## Версионирование

Используется [bump-my-version](https://github.com/callowayproject/bump-my-version).

```bash
# Патч: 0.2.0 → 0.2.1  (багфиксы)
bump-my-version bump patch

# Минор: 0.2.0 → 0.3.0  (новые фичи)
bump-my-version bump minor

# Мажор: 0.2.0 → 1.0.0  (breaking changes)
bump-my-version bump major
```

Команда автоматически обновляет версию в `pyproject.toml`, создаёт коммит и git-тег.
После этого запушить:

```bash
git push origin main --tags
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

- **Python 3.13**
- **aiogram 3.x** — Telegram Bot API
- **FastAPI + uvicorn** — REST API
- **SQLAlchemy 2.x async + asyncpg** — ORM + PostgreSQL
- **APScheduler 3.x** — планировщик напоминаний
- **dateparser** — парсинг дат на русском языке
- **Alembic** — миграции базы данных
- **bump-my-version** — версионирование
- **Docker + PostgreSQL 16**