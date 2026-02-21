# DAC Tournament (Iteration 1)

Стек: **Python 3.12, FastAPI, SQLAlchemy (async), Alembic, PostgreSQL 16, Bootstrap 5, Docker Compose**.

## Что уже реализовано (Итерация 2)
- Асинхронный FastAPI-проект с шаблонами Jinja2.
- Регистрация с проверкой Steam ID и защитой от дубля в БД.
- Поддержка Steam URL (profiles/id) и SteamID2.
- Интеграция с AutoChess API для автозаполнения:
  - Nickname in game
  - Current rank
  - Highest rank
- Авто-определение сезона (`mmr_sXX`, `max_mmr_sXX`) без хардкода номера.
- Назначение корзины по highest rank.
- Переключение языка ENG/RU с сохранением в cookie.
- Чат-бокс без регистрации (кд 10 секунд, длина до 1000).
- Базовая admin-панель с сессионной авторизацией по `admin_key` из `.env`:
  - редактирование этапов
  - открытие/закрытие регистрации
- Турнирный движок группового этапа:
  - `tournament_groups`, `group_members`, `group_game_results`
  - автоматическая жеребьевка на 64 участника (8 групп x 8)
  - автогенерация LobbyPW (4 цифры)
  - ввод результатов игр из админки (по местам 1..8)
  - автоначисление очков и tie-break сортировка (W, Top4, меньше 8 мест, место в последней игре).
- Ручное добавление участников в корзину `INVITED` из админки.
- Страница Tournament теперь показывает группы, текущую игру и очки.
- Docker-окружение: `docker compose up --build`.

## Быстрый старт (Windows 11 локально)
1. Скопируйте env:
   ```bash
   copy .env.example .env
   ```
2. (Опционально) впишите `STEAM_API_KEY`, если нужны vanity ID.
3. Запуск:
   ```bash
   docker compose up --build
   ```
4. Откройте: `http://0.0.0.0:8000/`
5. Админка (базовый поток): `http://0.0.0.0:8000/admin?admin_key=YOUR_ADMIN_KEY` (при валидном ключе автоматически создается signed cookie `admin_session` и выполняется редирект на `/admin`).
6. Запасной путь: `http://0.0.0.0:8000/admin/login` (ручной ввод `ADMIN_KEY` через форму).

## План следующих итераций
- **Итерация 3:** ручная жеребьевка с drag/drop и замены игроков в группах.
- **Итерация 4:** стадии playoff (1/16, 1/8, 1/4, semifinal/final), продвижение участников.
- **Итерация 5:** расширенный архив, донаты/правила из БД, аудит/история действий админа.

## Деплой на Ubuntu VDS (пошагово)
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl git

# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

git clone <YOUR_REPO_URL> dacarbelin
cd dacarbelin
cp .env.example .env
nano .env

# Запуск
docker compose up -d --build

# Проверка
docker compose ps
docker compose logs -f web
```

### Обновление версии
```bash
cd dacarbelin
git pull
docker compose up -d --build
```

### Рекомендации для production
- Поставьте reverse proxy (Nginx) и SSL (Let's Encrypt).
- Используйте сложные `ADMIN_KEY` и `SECRET_KEY`; доступ к `/admin/*` только через валидную admin-сессию (через ссылку с `admin_key` или через `/admin/login`) и signed session cookie.
- Дополнительно ограничьте доступ к `/admin` по IP через reverse proxy.
- Настройте регулярные backup базы PostgreSQL.

## Безопасный доступ к админке
1. В `.env` задайте сложные значения `ADMIN_KEY` и `SECRET_KEY` (не оставляйте `change_me`).
2. Базовый вход в админку: откройте `http://0.0.0.0:8000/admin?admin_key=YOUR_ADMIN_KEY`.
3. Если `admin_key` валиден, приложение создаст signed cookie `admin_session` (подпись на базе `SECRET_KEY`) и редиректнет на `/admin` без query-параметра.
4. Если `admin_key` невалиден и активной сессии нет, доступ к `/admin` будет отклонен.
5. Запасной путь остаётся доступным: `/admin/login` (POST-форма с `ADMIN_KEY`).
6. Для завершения сессии используйте `/admin/logout` (доступны GET и POST).
