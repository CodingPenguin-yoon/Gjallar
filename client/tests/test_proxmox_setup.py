import json

from gjallar_client.proxmox_setup import wizard


class SetupServer:
    def __init__(self, phase):
        self.row = {"attempt_id": "example-attempt", "phase": phase, "version": 3, "mode": "issue"}
        self.calls = []

    def proxmox_setup(self, action, *, attempt_id=None, body=None):
        self.calls.append((action, body))
        if body:
            assert body["expected_version"] == self.row["version"]
        if action == "login":
            self.row = {**self.row, "version": self.row["version"] + 1, "mfa_required": True}
        elif action == "mfa":
            assert body["otp"] == "123456"
            self.row = {**self.row, "version": self.row["version"] + 1, "mfa_required": False}
        elif action == "observe":
            self.row = {**self.row, "token_exists": True, "automatic_retry_allowed": False}
        elif action == "revoke":
            assert body["token_id"] == "test@pve!gjallar-example-attempt"
            self.row = {**self.row, "version": self.row["version"] + 1, "phase": "revoked"}
        return {"data": dict(self.row)}


def test_resume_observes_unknown_issue_without_reissuing():
    app = SetupServer("token_dispatching")
    inputs = iter(["observe"])
    secrets = iter(["", "synthetic-password", "123456"])
    output = []
    result = wizard(app, read=lambda _: next(inputs), password=lambda _: next(secrets),
                    output=output.append, attempt_id="example-attempt")
    assert [action for action, _ in app.calls] == ["status", "login", "mfa", "observe"]
    assert result["data"]["phase"] == "token_dispatching"
    assert "synthetic-password" not in json.dumps(result) + "".join(output)


def test_resume_revoke_requires_exact_user_input():
    app = SetupServer("revocation_pending")
    inputs = iter(["revoke", "test@pve!gjallar-example-attempt"])
    secrets = iter(["", "synthetic-password", "123456"])
    result = wizard(app, read=lambda _: next(inputs), password=lambda _: next(secrets),
                    output=lambda _: None, attempt_id="example-attempt")
    assert [action for action, _ in app.calls] == ["status", "login", "mfa", "observe", "revoke"]
    assert result["data"]["phase"] == "revoked"


def test_resume_does_not_revoke_on_empty_confirmation():
    app = SetupServer("active")
    inputs = iter(["revoke", ""])
    secrets = iter(["", "synthetic-password", "123456"])
    wizard(app, read=lambda _: next(inputs), password=lambda _: next(secrets),
           output=lambda _: None, attempt_id="example-attempt")
    assert all(action != "revoke" for action, _ in app.calls)
