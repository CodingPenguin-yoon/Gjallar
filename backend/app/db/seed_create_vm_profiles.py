"""Manual idempotent seed command for Create VM profiles."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.create_vm_profiles import count_create_vm_profiles, profile_rows_from_seed_definitions
from app.db.session import session_scope
from app.manifests.loader import load_builtin_profiles


@dataclass(frozen=True)
class CreateVmProfileSeedResult:
    inserted: int
    skipped: bool
    source: str = "db_seed"

    def to_dict(self) -> dict:
        return {"inserted": self.inserted, "skipped": self.skipped, "source": self.source}


def seed_create_vm_profiles(session: Session | None = None) -> CreateVmProfileSeedResult:
    """Insert initial Create VM profiles only when the table is empty."""
    if session is not None:
        if count_create_vm_profiles(session) > 0:
            return CreateVmProfileSeedResult(inserted=0, skipped=True)
        rows = profile_rows_from_seed_definitions(load_builtin_profiles())
        session.add_all(rows)
        return CreateVmProfileSeedResult(inserted=len(rows), skipped=False)

    with session_scope() as scoped_session:
        return seed_create_vm_profiles(scoped_session)


def main() -> int:
    result = seed_create_vm_profiles()
    print(result.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
