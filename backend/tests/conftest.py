import os

import pytest


EXPLICIT_PATH_ENV_KEYS = (
    "GJALLAR_IAC_ROOT",
)
DB_ENV_KEY = "GJALLAR_DATABASE_URL"
DB_SQLITE_TEST_ALLOW_KEY = "GJALLAR_ALLOW_SQLITE_FOR_TESTS"
TEST_SSH_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g "
    "gjallar@test"
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_inventory: opt into live Proxmox inventory env handling for backend tests",
    )


@pytest.fixture(autouse=True)
def _default_backend_inventory_mode(request, tmp_path):
    previous_mode = os.environ.get("GJALLAR_INVENTORY_MODE")
    previous_ssh_public_key = os.environ.get("GJALLAR_DEFAULT_SSH_PUBLIC_KEY")
    previous_database_url = os.environ.get(DB_ENV_KEY)
    previous_sqlite_test_allow = os.environ.get(DB_SQLITE_TEST_ALLOW_KEY)
    previous_paths = {key: os.environ.get(key) for key in EXPLICIT_PATH_ENV_KEYS}
    for key in EXPLICIT_PATH_ENV_KEYS:
        os.environ.pop(key, None)

    should_force_fake = request.node.get_closest_marker("live_inventory") is None
    if should_force_fake:
        os.environ["GJALLAR_INVENTORY_MODE"] = "fake"
    os.environ.setdefault("GJALLAR_DEFAULT_SSH_PUBLIC_KEY", TEST_SSH_PUBLIC_KEY)
    os.environ[DB_ENV_KEY] = f"sqlite:///{tmp_path / 'gjallar-test.db'}"
    os.environ[DB_SQLITE_TEST_ALLOW_KEY] = "1"

    from app.db.models import Base
    from app.db.seed_create_vm_profiles import seed_create_vm_profiles
    from app.db.session import get_engine, reset_session_cache

    reset_session_cache()
    Base.metadata.create_all(get_engine())
    seed_create_vm_profiles()

    try:
        yield
    finally:
        try:
            from app.db.session import reset_session_cache
        except ModuleNotFoundError:
            reset_session_cache = None
        if reset_session_cache is not None:
            reset_session_cache()

        if should_force_fake:
            if previous_mode is None:
                os.environ.pop("GJALLAR_INVENTORY_MODE", None)
            else:
                os.environ["GJALLAR_INVENTORY_MODE"] = previous_mode

        for key, value in previous_paths.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if previous_ssh_public_key is None:
            os.environ.pop("GJALLAR_DEFAULT_SSH_PUBLIC_KEY", None)
        else:
            os.environ["GJALLAR_DEFAULT_SSH_PUBLIC_KEY"] = previous_ssh_public_key
        if previous_database_url is None:
            os.environ.pop(DB_ENV_KEY, None)
        else:
            os.environ[DB_ENV_KEY] = previous_database_url
        if previous_sqlite_test_allow is None:
            os.environ.pop(DB_SQLITE_TEST_ALLOW_KEY, None)
        else:
            os.environ[DB_SQLITE_TEST_ALLOW_KEY] = previous_sqlite_test_allow

        try:
            from app.proxmox import inventory as inventory_module
        except ModuleNotFoundError:
            return

        inventory_module._DEFAULT_ADAPTER = None
        inventory_module._DEFAULT_ADAPTER_SIGNATURE = None
