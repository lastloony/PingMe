#!/bin/bash
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$APP_DIR/backups"
DATE=$(date +"%Y%m%d_%H%M%S")

cd "$APP_DIR"

echo "=== PingMe deploy: $DATE ==="

# --- Бэкап БД ---
echo "[1/4] Бэкап базы данных..."
mkdir -p "$BACKUP_DIR"
if docker compose ps postgres | grep -q "Up"; then
    docker compose exec -T postgres pg_dump \
        -U "${POSTGRES_USER:-pingme}" \
        "${POSTGRES_DB:-pingme}" \
        > "$BACKUP_DIR/backup_$DATE.sql"
    echo "      Бэкап сохранён: backups/backup_$DATE.sql"
    # Оставляем только последние 10 бэкапов
    ls -t "$BACKUP_DIR"/backup_*.sql | tail -n +11 | xargs -r rm
else
    echo "      ОШИБКА: Postgres не запущен, бэкап невозможен."
    echo "      Запусти сначала: docker compose up -d postgres"
    echo "      Или для первого деплоя запусти: docker compose up -d"
    exit 1
fi

# --- Git pull ---
echo "[2/4] Получение обновлений..."
git pull origin "$(git rev-parse --abbrev-ref HEAD)"

# --- Сборка образов ---
echo "[3/4] Сборка Docker-образов..."
docker compose build --no-cache bot

# --- Перезапуск ---
echo "[4/4] Перезапуск контейнеров..."
docker compose up -d --force-recreate bot

echo ""
echo "=== Деплой завершён ==="
echo "Логи: docker compose logs -f bot"