"""Определяет базовый класс ORM-моделей и общие миксины."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # Базовый класс для всех ORM моделей.
    pass
