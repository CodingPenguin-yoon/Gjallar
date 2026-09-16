import os

import pytest

DB_ENV_KEY = "GJALLAR_DATABASE_URL"
DB_SQLITE_TEST_ALLOW_KEY = "GJALLAR_ALLOW_SQLITE_FOR_TESTS"
SSH_ENV_KEYS = (
    "GJALLAR_DEFAULT_SSH_PUBLIC_KEY",
    "GJALLAR_DEFAULT_SSH_PUBLIC_KEY_B64",
    "GJALLAR_DEFAULT_SSH_PUBLIC_KEY_FILE",
)
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
    config.addinivalue_line(
        "markers",
        "postgresql: requires GJALLAR_POSTGRES_TEST_URL and validates PostgreSQL-specific coordination",
    )


@pytest.fixture(autouse=True)
def _default_backend_inventory_mode(request, tmp_path, monkeypatch):
    # Unit/contract tests must never probe real network addresses from fixtures.
    from app.vm_create import preflight as preflight_module
    from app.vm_create.ip_probe import IpProbeResult

    monkeypatch.setattr(preflight_module, "probe_ipv4", lambda address: IpProbeResult("no_reply"))
    previous_ssh_env = {key: os.environ.get(key) for key in SSH_ENV_KEYS}
    previous_database_url = os.environ.get(DB_ENV_KEY)
    previous_sqlite_test_allow = os.environ.get(DB_SQLITE_TEST_ALLOW_KEY)
    for key in SSH_ENV_KEYS:
        os.environ.pop(key, None)

    should_force_fake = request.node.get_closest_marker("live_inventory") is None
    if should_force_fake:
        from app.proxmox import inventory as inventory_module
        from app.vm_create import preflight as preflight_module

        fake_adapter = inventory_module.FakeProxmoxInventoryAdapter()
        monkeypatch.setattr(inventory_module, "get_default_inventory_adapter", lambda: fake_adapter)
        monkeypatch.setattr(preflight_module, "get_default_inventory_adapter", lambda: fake_adapter)
    os.environ["GJALLAR_DEFAULT_SSH_PUBLIC_KEY"] = TEST_SSH_PUBLIC_KEY
    os.environ[DB_ENV_KEY] = f"sqlite:///{tmp_path / 'gjallar-test.db'}"
    os.environ[DB_SQLITE_TEST_ALLOW_KEY] = "1"

    # Each test has an isolated database, including durable target locks.

    from app.db.metadata import Base
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

        for key, value in previous_ssh_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
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
            inventory_module = None

        if inventory_module is not None:
            inventory_module._DEFAULT_ADAPTER = None
            inventory_module._DEFAULT_ADAPTER_SIGNATURE = None
