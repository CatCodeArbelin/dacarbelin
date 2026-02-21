# DAC Tournament (Iteration 1)

Стек: **Python 3.12, FastAPI, SQLAlchemy (async), Alembic, PostgreSQL 16, Bootstrap 5, Docker Compose**.

## Матрица соответствия «ТЗ → реализовано/не реализовано»

| Блок ТЗ | Статус | Что сделано |
|---|---|---|
| 1) Ручная жеребьевка + гибкое редактирование составов групп | ✅ Реализовано | Добавлены ручное создание сетки групп, стартовое распределение участников и формы add/remove/move/swap в админке. |
| 2) Полный цикл стадий playoff (56→32→16→8) + ручные override | ✅ Реализовано | Генератор стадий работает по фактической схеме: I этап 1/8 (56, 7x8, top-3) → II этап 1/4 (32, 4x8, top-4) → III этап полуфинальные группы (16, 2x8, top-4) → Финал (8, правило 22+победа). |
| 3) Расширенное управление архивом турнирных сеток | ✅ Реализовано | Архив расширен полями champion/bracket payload/published и обновлен UI редактирования/показа. |

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
- Турнирный движок playoff-стадий:
  - I этап 1/8: 56 участников, 7 групп по 8, проход top-3 из каждой группы.
  - II этап 1/4: 32 участника, 4 группы по 8, проход top-4 из каждой группы.
  - III этап (полуфинальные группы): 16 участников, 2 группы по 8, проход top-4 из каждой группы.
  - Финал: 8 участников, special scoring: 22 очка + победа в следующей игре.
- Docker-окружение: `docker compose up --build`.

## Единый сценарий запуска (Windows 11 и Ubuntu VDS)

Ниже один и тот же набор переменных и шагов, который работает и локально на Windows 11, и на Ubuntu VDS.

### 1) Создайте `.env` из шаблона

**Windows (PowerShell):**
```powershell
copy .env.example .env
```

**Ubuntu (bash):**
```bash
cp .env.example .env
```

### 2) Заполните `.env` (реальный пример)

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/dac
ADMIN_KEY=admin_2026_super_secret
SECRET_KEY=secret_2026_super_long_random_string
STEAM_API_KEY=
APP_HOST=0.0.0.0
APP_PORT=8000
```

Примечания:
- `STEAM_API_KEY` можно оставить пустым, если не используете vanity ID.
- Для внешнего доступа к VDS обычно оставляют `APP_HOST=0.0.0.0`.
- В production обязательно задайте сложные `ADMIN_KEY` и `SECRET_KEY`.

### 3) Запуск через Docker Compose

```bash
docker compose up --build
```

Для фонового режима (чаще на VDS):
```bash
docker compose up -d --build
```

### 4) Проверка

```bash
docker compose ps
docker compose logs -f web
```

Приложение доступно по адресу: `http://<host>:8000/`.

Админка:
- Основной вход: `http://<host>:8000/admin?admin_key=admin_2026_super_secret`
- Резервный вход через форму: `http://<host>:8000/admin/login`

### 5) Обновление версии

```bash
git pull
docker compose up -d --build
```

## Быстрое заполнение 64 участниками (для теста жеребьевки)

Скрипт `scripts/seed_64_participants.py` требует переменные окружения `DATABASE_URL` и `ADMIN_KEY`.

Предпочтительный вариант (внутри контейнера `web`, где env уже подхватывается из `.env`):

```bash
docker compose exec web python scripts/seed_64_participants.py
```

Локальный запуск из venv (с предварительным экспортом env-переменных):

```bash
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/dac
export ADMIN_KEY=local_seed_admin_key
python scripts/seed_64_participants.py
```

Скрипт добавляет 64 уникальных участника с рандомными никами, MMR/рангами и корзинами.

## План следующих итераций
- **Итерация 3:** ручная жеребьевка с drag/drop и замены игроков в группах.
- **Итерация 4:** завершена — стадии playoff синхронизированы с боевой логикой (56→32→16→8) и правилами продвижения.
- **Итерация 5:** расширенный архив, донаты/правила из БД, аудит/история действий админа.

## Безопасный доступ к админке
1. В `.env` задайте сложные значения `ADMIN_KEY` и `SECRET_KEY` (не оставляйте `change_me`).
2. Базовый вход в админку: откройте `http://0.0.0.0:8000/admin?admin_key=YOUR_ADMIN_KEY`.
3. Если `admin_key` валиден, приложение создаст signed cookie `admin_session` (подпись на базе `SECRET_KEY`) и редиректнет на `/admin` без query-параметра.
4. Если `admin_key` невалиден и активной сессии нет, доступ к `/admin` будет отклонен.
5. Запасной путь остаётся доступным: `/admin/login` (POST-форма с `ADMIN_KEY`).
6. Для завершения сессии используйте `/admin/logout` (доступны GET и POST).
