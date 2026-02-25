# Бэклог

## [IDEA] Django Bot Manager — веб-панель управления ботами

**Статус:** идея, не начато
**Приоритет:** низкий (отложено)

### Суть

Отдельный Django-сервис, который выступает control plane для ботов (в т.ч. PingMe).
Бот остаётся самостоятельным микросервисом, Django — наблюдатель и управляющий.

### Что должен уметь Django-менеджер

- Хранить настройки ботов: токены, специальные команды, параметры
- Вести список пользователей каждого бота
- Отображать историю сообщений (что пользователи слали боту) — без прямого доступа к БД бота
- Хранить логи ошибок
- Перезапускать/останавливать/запускать ботов через Docker API

### Архитектура

```
[Telegram] ←polling→ [Bot (aiogram+FastAPI)]
                              ↕ HTTP events
                         [Django Manager]
                              ↕
                         [Docker API] → restart/stop/start контейнеров
```

**Django модели:**
- `Bot` — токен, имя, статус (running/stopped), дата последнего запуска
- `BotUser` — user_id, username, привязка к боту
- `MessageLog` — user_id, текст, направление (in/out), timestamp
- `ErrorLog` — текст ошибки, traceback, timestamp, бот

**Интеграция с ботом (минимальные изменения):**

1. Event publisher — после каждого входящего сообщения POST на Django:
```python
async def publish_event(user_id, text, direction="in"):
    async with aiohttp.ClientSession() as s:
        await s.post(DJANGO_WEBHOOK_URL, json={
            "bot_token": settings.bot_token,
            "user_id": user_id,
            "text": text,
            "direction": direction,
        })
```

2. Error handler — кастомный `logging.Handler`, шлёт ошибки в Django

3. Конфиг — токен и параметры по-прежнему из `.env`, опционально можно тянуть из Django API при старте

**Перезапуск через Docker API (Django side):**
```python
import docker
client = docker.from_env()
client.containers.get("pingme_bot").restart()
```

### Что НЕ меняется в боте

- Polling остаётся (webhook нужен только если Django будет роутить апдейты)
- БД бота остаётся отдельной — Django читает данные через FastAPI бота
- Вся бизнес-логика остаётся в боте

### Шаги реализации (когда придёт время)

1. Создать Django-проект с моделями `Bot`, `BotUser`, `MessageLog`, `ErrorLog`
2. Добавить в бот `publish_event()` и кастомный logging handler
3. Добавить в Django endpoint `/internal/events/` и `/internal/errors/`
4. Настроить Django Admin для визуализации
5. Добавить управление контейнерами через `docker-py`
6. Добавить аутентификацию на FastAPI бота (токен) если Django будет дёргать его API