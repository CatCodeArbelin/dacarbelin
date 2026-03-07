# DAC Tournament (Iteration 1)

Стек: **Python 3.12, FastAPI, SQLAlchemy (async), Alembic, PostgreSQL 16, Bootstrap 5, Docker Compose**.

## Матрица соответствия «ТЗ → реализовано/не реализовано»

| Блок ТЗ | Статус | Что сделано |
|---|---|---|
| 1) Ручная жеребьевка + гибкое редактирование составов групп | ✅ Реализовано | Добавлены ручное создание сетки групп, стартовое распределение участников и формы add/remove/move/swap в админке. |
| 2) Полный цикл стадий playoff (56→32→16→8) + ручные override | ✅ Реализовано | Генератор стадий работает по фактической схеме: I этап (56, top-3) → II этап (32, top-4) → III этап (16, top-4) → Финал (8, 22+победа). |
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
  - автоматическая жеребьевка на 56 участников (7 групп x 8), 3 игры в группе
  - автогенерация LobbyPW (4 цифры)
  - ввод результатов игр из админки (по местам 1..8)
  - автоначисление очков и tie-break сортировка (W, Top4, меньше 8 мест, место в последней игре).
- Ручное добавление участников в корзину `INVITED` из админки.
- Страница Tournament теперь показывает группы, текущую игру и очки.
- Турнирный движок playoff-стадий:
  - I этап: 56 участников (7 групп по 8), проход top-3 из каждой группы.
  - II этап: 32 участника (4 группы по 8), проход top-4 из каждой группы.
  - III этап: 16 участников (2 группы по 8), проход top-4 из каждой группы.
  - Финал: 8 участников, правило 22+победа.
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

Приложение доступно по адресу: `http://0.0.0.0:8000/`.

Админка:
- Основной вход: `http://0.0.0.0:8000/admin?admin_key=admin_2026_super_secret`
- Для судей используйте одноразовую подписанную ссылку из интерфейса `/admin` (без передачи сырого `admin_key`).
- Резервный вход через форму: `http://0.0.0.0:8000/admin/login`

### 5) Обновление версии

```bash
git pull
docker compose up -d --build
```


## Проверка миграций и запуска без Docker

Если Docker недоступен, можно быстро проверить цепочку Alembic-миграций (offline SQL) и импорт приложения:

```bash
bash scripts/check_migrations_and_startup.sh
```

Скрипт проверяет, что:
- все миграции последовательно собираются до `head`;
- приложение FastAPI корректно импортируется (базовая проверка запуска).

## Запуск тестов

Проект использует `pytest` (с тестами в `tests/`).

Запуск всех тестов:

```bash
pytest
```

Запуск выборочно (пример для новых сценариев playoff/direct invites):

```bash
pytest tests/test_tournament_auto_draw.py tests/test_tournament_workflows.py tests/test_playoff_match_limits.py tests/test_participants_direct_invites.py
```

## Быстрое заполнение турнира: 56 обычных + 11 direct invite

Скрипт `scripts/seed_tournament_56_plus_11.py` требует переменные окружения `DATABASE_URL` и `ADMIN_KEY`.

Предпочтительный вариант (внутри контейнера `web`, где env уже подхватывается из `.env`).

> ⚠️ Выполняйте команду после `docker compose up --build` (или после `docker compose build web` + `docker compose up`), чтобы в контейнере уже была актуальная версия `scripts/`.

```bash
docker compose exec web python scripts/seed_tournament_56_plus_11.py
```

Локальный запуск из venv (с предварительным экспортом env-переменных):

```bash
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/dac
export ADMIN_KEY=local_seed_admin_key
python scripts/seed_tournament_56_plus_11.py
```

Скрипт подготавливает сценарий для II этапа 21+11: добавляет 56 обычных уникальных участников с рандомными никами, MMR/рангами и корзинами, а также 11 direct invite участников (`basket=invited`, `direct_invite_stage=stage_2`), из которых формируется сетка 32 (21 прошедший + 11 инвайтов).

`direct_invite_stage` — это специальный флаг для логики direct invite (например, автоподбор инвайтов в `stage_2`). Он **не** является универсальным механизмом ручного переноса игрока между playoff-стадиями: для явного переноса используйте `/admin/user/reassign`.

## План следующих итераций
- **Итерация 3:** ручная жеребьевка с drag/drop и замены игроков в группах.
- **Итерация 4:** завершена — стадии playoff синхронизированы с боевой логикой (56→32→16→8) и правилами продвижения.
- **Итерация 5:** расширенный архив, донаты/правила из БД, аудит/история действий админа.

## Безопасный доступ к админке
1. В `.env` задайте сложные значения `ADMIN_KEY` и `SECRET_KEY` (не оставляйте `change_me`).
2. Базовый вход в админку: откройте `http://0.0.0.0:8000/admin?admin_key=YOUR_ADMIN_KEY`.
3. Если `admin_key` валиден, приложение создаст signed cookie `admin_session` (подпись на базе `SECRET_KEY`) и редиректнет на `/admin` без query-параметра.
4. Если `admin_key` невалиден и активной сессии нет, произойдёт редирект на `/admin/login?msg=msg_admin_login_failed`.
5. Для судей используйте одноразовую подписанную ссылку вида `/admin?judge_token=...`, сгенерированную в админ-панели.
6. Запасной путь остаётся доступным: `/admin/login` (POST-форма с `ADMIN_KEY`).
7. Для завершения сессии используйте `/admin/logout` (доступны GET и POST).

## TinyMCE: настройка Approved Domains для админки

Если редактор в `/admin` не загружается с ошибкой домена, добавьте домены в кабинете Tiny для ключа `TINY_MCE_API_KEY`.

1. Войдите в Tiny account владельца ключа `9z687o5rskzyvrw1mirxiiaoal4futppl1u9sx7t5ajlg6f3`.
2. Откройте настройки API key и раздел **Approved Domains**.
3. Добавьте фактический домен админки (включая нужный поддомен, например `admin.example.com`).
4. Для локального теста добавьте `localhost` и/или `127.0.0.1` с нужным портом (например `localhost:8000`) по правилам Tiny.
5. Сохраните список доменов, подождите применение настроек и обновите страницу с очисткой кэша.
