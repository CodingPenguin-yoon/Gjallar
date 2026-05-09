import os

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_inventory: opt into live Proxmox inventory env handling for backend tests",
    )


@pytest.fixture(autouse=True)
def _default_backend_inventory_mode(request):
    previous_mode = os.environ.get("GJALLAR_INVENTORY_MODE")
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

        try:
            from app.proxmox import inventory as inventory_module
        except ModuleNotFoundError:
            return

        inventory_module._DEFAULT_ADAPTER = None
        inventory_module._DEFAULT_ADAPTER_SIGNATURE = None
