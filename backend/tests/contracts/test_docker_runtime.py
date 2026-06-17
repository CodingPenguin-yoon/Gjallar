"""Docker runtime contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_dockerfile_uses_startup_entrypoint_before_uvicorn():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY docker/entrypoint.sh /app/entrypoint.sh" in dockerfile
    assert "RUN chmod +x /app/entrypoint.sh" in dockerfile
    assert 'ENTRYPOINT ["/app/entrypoint.sh"]' in dockerfile
    assert 'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]' in dockerfile


def test_entrypoint_runs_migration_seed_then_requested_command():
    entrypoint = (REPO_ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    migration_index = entrypoint.index("alembic -c /app/backend/alembic.ini upgrade head")
    seed_index = entrypoint.index("python -m app.db.seed_create_vm_profiles")
    bootstrap_index = entrypoint.index("python -m app.auth.users bootstrap-admin-from-env")
    exec_index = entrypoint.index('exec "$@"')

    assert 'set -eu' in entrypoint
    assert "GJALLAR_SKIP_STARTUP_INIT" in entrypoint
    assert migration_index < seed_index < bootstrap_index < exec_index


def test_entrypoint_is_valid_sh_syntax():
    result = subprocess.run(
        ["sh", "-n", str(REPO_ROOT / "docker" / "entrypoint.sh")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
