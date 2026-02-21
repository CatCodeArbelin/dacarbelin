import os
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path для корректного импорта app.
sys.path.append(str(Path(__file__).resolve().parents[1]))
# Задаем обязательные переменные окружения для инициализации настроек.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ADMIN_KEY", "test_admin")
