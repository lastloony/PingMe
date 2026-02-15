# Инструкция по установке и запуску PingMe

## Шаг 1: Создание виртуального окружения

```bash
python -m venv venv
```

## Шаг 2: Активация виртуального окружения

```bash
venv\Scripts\activate
```

## Шаг 3: Установка зависимостей

```bash
pip install -r requirements.txt
```

## Шаг 4: Настройка переменных окружения

1. Скопируйте файл `.env.example` в `.env`:
```bash
copy .env.example .env
```

2. Откройте `.env` и укажите ваш токен бота:
```
BOT_TOKEN=ваш_токен_от_BotFather
```

Чтобы получить токен:
- Откройте Telegram
- Найдите @BotFather
- Отправьте команду /newbot
- Следуйте инструкциям
- Скопируйте полученный токен в .env

## Шаг 5: Запуск приложения

```bash
python main.py
```

Приложение запустит:
- Telegram бота (polling)
- FastAPI сервер на http://localhost:8000

## Проверка работы

1. Откройте браузер: http://localhost:8000
2. Вы должны увидеть: `{"status":"ok","service":"PingMe API","version":"0.1.0"}`
3. API документация: http://localhost:8000/docs
4. Найдите вашего бота в Telegram и отправьте /start

## Команды бота

- `/start` - Начать работу
- `/help` - Справка
- `/remind` - Создать напоминание
- `/list` - Список напоминаний
- `/delete [ID]` - Удалить напоминание
- `/cancel` - Отменить действие

## Структура проекта

```
pingme/
├── app/
│   ├── api/              # FastAPI приложение
│   │   ├── app.py        # Основной файл API
│   │   ├── routes.py     # Маршруты API
│   │   └── schemas.py    # Pydantic схемы
│   ├── bot/              # Telegram бот
│   │   ├── bot.py        # Инициализация бота
│   │   └── handlers/     # Обработчики команд
│   ├── database/         # База данных
│   │   ├── base.py       # Настройка SQLAlchemy
│   │   └── models.py     # Модели данных
│   ├── services/         # Сервисы
│   │   └── scheduler.py  # Планировщик напоминаний
│   └── config.py         # Конфигурация
├── main.py               # Точка входа
├── requirements.txt      # Зависимости
├── .env                  # Переменные окружения
└── README.md
```
