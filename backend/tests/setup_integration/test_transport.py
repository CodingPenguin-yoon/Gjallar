import socket
import ssl

import pytest

from app.setup_integration.contracts import SetupError
from app.setup_integration.transport import ProxmoxSetupTransport


def resolver(address):
    return lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 8006))]


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "224.0.0.1", "0.0.0.0", "::1", "::ffff:127.0.0.1"])
def test_dns_to_unsafe_destination_is_rejected_before_credentials(address):
    with pytest.raises(SetupError) as error:
        ProxmoxSetupTransport("https://pve.example.test:8006/api2/json", resolver=resolver(address))
    assert error.value.code == "PROXMOX_ENDPOINT_REJECTED"


def test_tls_failure_never_sends_credentials(monkeypatch):
    transport = ProxmoxSetupTransport("https://pve.example.test:8006/api2/json", resolver=resolver("192.168.100.5"))
    seen = []
    class PlainSocket:
        def close(self):
            seen.append("closed")
    class Context:
        def wrap_socket(self, plain, *, server_hostname):
            assert server_hostname == "pve.example.test"
            raise ssl.SSLError("synthetic-sensitive-upstream-error")
    transport.context = Context()
    monkeypatch.setattr(socket, "create_connection", lambda target, **kwargs: seen.append(target) or PlainSocket())
    with pytest.raises(SetupError) as error:
        transport.request("POST", "/access/ticket", data={"password": "synthetic-password"})
    assert "synthetic" not in str(error.value)
    assert seen == [("192.168.100.5", 8006), "closed"]
    assert error.value.code == "PROXMOX_TLS_FAILED"
