"""Shared SQLAlchemy declarative base for modular metadata registration."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for Gjallar-owned database models."""
