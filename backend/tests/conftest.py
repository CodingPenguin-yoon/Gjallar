import os

import pytest


EXPLICIT_PATH_ENV_KEYS = (
    "GJALLAR_IAC_ROOT",
    "REMOTE_IAC_REPO",
    "REMOTE_IaC_repo",
    "GJALLAR_TF_STATE_ROOT",
    "GJALLAR_TERRAFORM_STATE_ROOT",
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_inventory: opt into live Proxmox inventory env handling for backend tests",
    )


@pytest.fixture(autouse=True)
def _default_backend_inventory_mode(request):
    previous_mode = os.environ.get("GJALLAR_INVENTORY_MODE")
    previous_paths = {key: os.environ.get(key) for key in EXPLICIT_PATH_ENV_KEYS}
    for key in EXPLICIT_PATH_ENV_KEYS:
        os.environ.pop(key, None)

    should_force_fake = request.node.get_closest_marker("live_inventory") is None
    if should_force_fake:
        os.environ["GJALLAR_INVENTORY_MODE"] = "fake"

    try:
        yield
    finally:
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

        try:
            from app.proxmox import inventory as inventory_module
        except ModuleNotFoundError:
            return

        inventory_module._DEFAULT_ADAPTER = None
        inventory_module._DEFAULT_ADAPTER_SIGNATURE = None
