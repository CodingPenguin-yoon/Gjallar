"""Compose SQLAlchemy metadata from the monolith's owned modules."""

from app.db.base import Base
from app.db import models as legacy_models  # noqa: F401
from app.operations.core.infrastructure import models as operation_models  # noqa: F401
from app.operations.recovery.infrastructure import models as recovery_models  # noqa: F401

__all__ = ["Base"]
