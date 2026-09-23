import json
import subprocess

import pytest

from gjallar_client.bootstrap import Bootstrap, Docker, compose_config
from gjallar_client.connections import atomic_json, file_lock
from gjallar_client.errors import ClientError

APP = "sha256:" + "a" * 64
PG = "sha256:" + "b" * 64
NEXT = "sha256:" + "c" * 64
PASSWORD = "test-admin-secret"


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.volumes = {}
        self.state = "schema_ready"
        self.running = False
        self.fail = None
        self.admin_calls = 0

    def __call__(self, args, *, input_text=None):
        self.calls.append((list(args), input_text))
        if self.fail and self.fail(args):
            raise ClientError("MOCK_FAILURE", "실행 중단")
        if args[:2] == ["compose", "version"]:
            return "2.39.0"
        if args[0] == "context":
            return "unix:///docker.sock"
        if args[0] == "info":
            return json.dumps({"OSType": "linux", "Architecture": "aarch64"})
        if args[0] == "pull":
            return ""
        if args[:2] == ["image", "inspect"]:
            return json.dumps({"Id": PG if args[2].startswith("postgres:") else NEXT if args[2] == "gjallar:next" else APP, "Os": "linux", "Architecture": "arm64"})
        if args[:2] == ["volume", "ls"]:
            return "\n".join(self.volumes)
        if args[:2] == ["volume", "create"]:
            self.volumes[args[-1]] = args[-2].split("=", 1)[1]
            return args[-1]
        if args[:2] == ["volume", "inspect"]:
            return json.dumps({"Labels": {"org.gjallar.installation": self.volumes[args[2]]}})
        if "ps" in args:
            if "--services" in args:
                return "postgres\ngjallar" if self.running else "postgres"
            return json.dumps([{ "Service": "gjallar", "State": "running" if self.running else "exited", "Health": "healthy"}])
        if args[-1] == "setup-admin":
            self.admin_calls += 1
            assert json.loads(input_text)["password"] == PASSWORD
            self.state = "ready"
            return json.dumps({"ok": True, "state": "created"})
        if args[-1] == "status":
            return json.dumps({"ok": True, "state": self.state})
        if args[-1] in {"check-ready", "init-schema"}:
            return json.dumps({"ok": True, "state": self.state})
        if "up" in args and args[-1] == "gjallar":
            self.running = True
        if "stop" in args and args[-1] == "gjallar":
            self.running = False
        return ""


@pytest.fixture
def setup(tmp_path):
    runner = FakeDocker()
    bootstrap = Bootstrap(tmp_path / "install", runner, port_check=lambda port, bind_address: None)
    return bootstrap, runner


def admin():
    return {"username": "admin", "password": PASSWORD}


def test_install_start_status_stop_preserves_data_and_no_argv_secrets(setup):
    bootstrap, runner = setup
    result = bootstrap.install(administrator=admin)
    assert result["url"] == "http://127.0.0.1:8000"
    original = bootstrap.manifest_path.read_bytes()
    secrets_before = {p.name: p.read_bytes() for p in (bootstrap.directory / "secrets").iterdir()}
    assert PASSWORD not in " ".join(" ".join(args) for args, _ in runner.calls)
    assert PASSWORD not in json.dumps(result)
    for name in ("installation.json", "compose.json"):
        content = (bootstrap.directory / name).read_text()
        assert PASSWORD not in content
        for value in secrets_before.values():
            assert value.decode() not in content
    config = compose_config(bootstrap.load())
    assert config["services"]["gjallar"]["ports"] == ["127.0.0.1:8000:8000"]
    assert "ports" not in config["services"]["postgres"]
    assert config["services"]["gjallar"]["entrypoint"][-1] == "app.installation.serve"
    assert bootstrap.service("status")["services"][0]["State"] == "running"
    bootstrap.service("stop")
    runner.calls.clear()
    bootstrap.service("start")
    bootstrap.install(administrator=lambda: pytest.fail("must not ask for existing administrator"))
    assert not any(args[-1] in {"init-schema", "setup-admin"} for args, _ in runner.calls)
    assert runner.admin_calls == 1
    assert bootstrap.manifest_path.read_bytes() == original
    assert secrets_before == {p.name: p.read_bytes() for p in (bootstrap.directory / "secrets").iterdir()}
    assert not any("down" in args or "rm" in args or "prune" in args for args, _ in runner.calls)


@pytest.mark.parametrize("phase", ["init-schema", "setup-admin", "check-ready", "gjallar"])
def test_interrupted_install_reuses_volume_secrets_and_admin(setup, phase):
    bootstrap, runner = setup
    runner.fail = lambda args: args[-1] == phase
    with pytest.raises(ClientError):
        bootstrap.install(administrator=admin)
    before = {p.name: p.read_bytes() for p in (bootstrap.directory / "secrets").iterdir()}
    identity = bootstrap.load()["id"]
    runner.fail = None
    assert bootstrap.install(administrator=admin)["state"] == "running"
    assert bootstrap.load()["id"] == identity
    assert before == {p.name: p.read_bytes() for p in (bootstrap.directory / "secrets").iterdir()}
    assert len(runner.volumes) == 1 and runner.admin_calls == 1


def test_admin_commit_response_loss_does_not_duplicate(setup):
    bootstrap, runner = setup
    original = runner.__call__
    lost = True
    def call(args, **kwargs):
        nonlocal lost
        result = original(args, **kwargs)
        if args[-1] == "setup-admin" and lost:
            lost = False
            raise ClientError("LOST", "응답 유실")
        return result
    bootstrap.runner = call
    with pytest.raises(ClientError):
        bootstrap.install(administrator=admin)
    bootstrap.install(administrator=lambda: pytest.fail("already initialized"))
    assert runner.admin_calls == 1


def test_unknown_existing_path_missing_secret_volume_conflict(setup):
    bootstrap, runner = setup
    bootstrap.directory.mkdir(mode=0o700)
    (bootstrap.directory / "existing.txt").write_text("keep")
    with pytest.raises(ClientError) as error:
        bootstrap.install(administrator=admin)
    assert error.value.code == "PATH_NOT_EMPTY"
    assert (bootstrap.directory / "existing.txt").read_text() == "keep"
    assert not runner.volumes


def test_missing_existing_volume_never_recreated(setup):
    bootstrap, runner = setup
    bootstrap.install(administrator=admin)
    runner.volumes.clear()
    runner.calls.clear()
    with pytest.raises(ClientError) as error:
        bootstrap.service("start")
    assert error.value.code == "VOLUME_MISSING"
    assert not any(args[:2] == ["volume", "create"] for args, _ in runner.calls)


def test_missing_secret_never_regenerated(setup):
    bootstrap, runner = setup
    bootstrap.install(administrator=admin)
    path = bootstrap.directory / "secrets" / "database_url"
    path.unlink()
    with pytest.raises(ClientError) as error:
        bootstrap.install(administrator=admin)
    assert error.value.code == "SECRET_MISSING"
    assert not path.exists()


def test_bad_volume_label_preserves_existing_data(setup):
    bootstrap, runner = setup
    bootstrap.install(administrator=admin)
    name = bootstrap.load()["volume"]
    runner.volumes[name] = "other"
    runner.calls.clear()
    with pytest.raises(ClientError) as error:
        bootstrap.service("start")
    assert error.value.code == "VOLUME_CONFLICT"
    assert not any("up" in args or "run" in args for args, _ in runner.calls)


def test_busy_lock(setup):
    bootstrap, _ = setup
    bootstrap.directory.mkdir(mode=0o700)
    with file_lock(bootstrap.directory / ".installation.lock"):
        with pytest.raises(ClientError) as error:
            bootstrap.install(administrator=admin)
    assert error.value.code == "STORAGE_BUSY"


def test_upgrade_schema_mismatch_keeps_original_and_does_not_stop(setup):
    bootstrap, runner = setup
    bootstrap.install(administrator=admin)
    before = bootstrap.manifest_path.read_bytes()
    runner.calls.clear()
    runner.fail = lambda args: any("upgrade-candidate.json" in arg for arg in args)
    with pytest.raises(ClientError):
        bootstrap.upgrade("gjallar:next")
    assert bootstrap.manifest_path.read_bytes() == before
    assert not any("stop" in args for args, _ in runner.calls)
    assert not any("init-schema" in args for args, _ in runner.calls)


def test_validated_images_keep_a_content_named_local_tag(setup):
    bootstrap, runner = setup
    bootstrap.install(administrator=admin)
    for image_id in (APP, PG):
        assert (["image", "tag", image_id, "gjallar-pinned:" + image_id.replace(":", "-")], None) in runner.calls


def test_upgrade_checks_running_server_when_original_image_is_unavailable(setup):
    bootstrap, runner = setup
    bootstrap.install(administrator=admin)
    runner.calls.clear()
    runner.fail = lambda args: "run" in args and not any("upgrade-candidate.json" in arg for arg in args) and "stop" not in args and runner.running
    assert bootstrap.upgrade("gjallar:next")["state"] == "running"
    assert bootstrap.load()["image"] == NEXT
    assert any("exec" in args and args[-1] == "check-ready" for args, _ in runner.calls)


def test_upgrade_and_resume_pair_write_failure(setup, monkeypatch):
    bootstrap, runner = setup
    bootstrap.install(administrator=admin)
    from gjallar_client import bootstrap as module
    real = module.atomic_json
    failed = False
    def interrupted(path, value):
        nonlocal failed
        if path == bootstrap.manifest_path and value["image"] == NEXT and not failed:
            failed = True
            raise OSError("interrupted")
        real(path, value)
    monkeypatch.setattr(module, "atomic_json", interrupted)
    with pytest.raises(OSError):
        bootstrap.upgrade("gjallar:next")
    assert bootstrap.service("status")["state"] == "upgrade_pending"
    bootstrap.service("start")
    assert bootstrap.load()["image"] == NEXT
    assert not (bootstrap.directory / "upgrade.json").exists()
    assert len(list(bootstrap.directory.glob("before-upgrade-*"))) == 1
    assert runner.admin_calls == 1


def test_install_does_not_implicitly_upgrade(setup):
    bootstrap, _ = setup
    bootstrap.install(administrator=admin)
    with pytest.raises(ClientError) as error:
        bootstrap.install(image="gjallar:next", administrator=admin)
    assert error.value.code == "UPGRADE_REQUIRED"


def test_docker_runner_hides_output_and_sanitizes_environment(monkeypatch):
    monkeypatch.setenv("GJALLAR_DATABASE_URL", PASSWORD)
    monkeypatch.setenv("COMPOSE_FILE", "evil.yml")
    monkeypatch.setattr("shutil.which", lambda _: "/bin/docker")
    def run(args, **kwargs):
        assert PASSWORD not in " ".join(args)
        assert "GJALLAR_DATABASE_URL" not in kwargs["env"] and "COMPOSE_FILE" not in kwargs["env"]
        return subprocess.CompletedProcess(args, 1, PASSWORD, PASSWORD)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ClientError) as error:
        Docker()(["info"])
    assert PASSWORD not in str(error.value)


def test_missing_docker_is_guidance_only(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(ClientError) as error:
        Docker()(["compose", "version"])
    assert error.value.code == "DOCKER_MISSING"


def test_preflight_remote_context_and_occupied_port(setup):
    bootstrap, runner = setup
    bootstrap.runner = lambda args, **kwargs: "tcp://remote:2375" if args[0] == "context" else runner(args, **kwargs)
    with pytest.raises(ClientError) as error:
        bootstrap.install(administrator=admin)
    assert error.value.code == "REMOTE_DOCKER_REJECTED"
    assert not bootstrap.directory.exists()
    bootstrap.runner = runner
    bootstrap.port_check = lambda port, bind_address: (_ for _ in ()).throw(ClientError("PORT_IN_USE", "충돌"))
    with pytest.raises(ClientError):
        bootstrap.install(administrator=admin)
    assert not bootstrap.manifest_path.exists() and not runner.volumes


def test_missing_volume_after_interrupted_initialization_is_not_recreated(setup):
    bootstrap, runner = setup
    runner.fail = lambda args: args[-1] == "setup-admin"
    with pytest.raises(ClientError):
        bootstrap.install(administrator=admin)
    assert bootstrap.load()["state"] == "storage_ready"
    runner.fail = None
    runner.volumes.clear()
    runner.calls.clear()
    with pytest.raises(ClientError) as error:
        bootstrap.install(administrator=admin)
    assert error.value.code == "VOLUME_MISSING"
    assert not any(args[:2] == ["volume", "create"] for args, _ in runner.calls)


def test_stop_during_pending_upgrade_never_starts_services(setup):
    bootstrap, runner = setup
    bootstrap.install(administrator=admin)
    before = bootstrap.load()
    candidate = {**before, "image": NEXT}
    atomic_json(bootstrap.directory / "upgrade.json", {"before": before, "candidate": candidate})
    runner.calls.clear()
    assert bootstrap.service("stop")["state"] == "stopped"
    assert not any("up" in args or "run" in args for args, _ in runner.calls)
    assert (bootstrap.directory / "upgrade.json").exists()


def test_external_web_binding_survives_resume_start_and_upgrade(setup):
    bootstrap, runner = setup
    checks = []
    bootstrap.port_check = lambda port, address: checks.append((port, address))
    options = dict(bind_address="0.0.0.0")
    runner.fail = lambda args: args[-1] == "setup-admin"
    with pytest.raises(ClientError):
        bootstrap.install(administrator=admin, **options)
    secrets_before = {p.name: p.read_bytes() for p in (bootstrap.directory / "secrets").iterdir()}
    runner.fail = None
    result = bootstrap.install(administrator=admin, **options)
    assert result["url"] == "http://127.0.0.1:8000"
    assert result["bind_address"] == "0.0.0.0"
    assert bootstrap.load()["version"] == 3
    config = compose_config(bootstrap.load())
    assert config["services"]["gjallar"]["ports"] == ["0.0.0.0:8000:8000"]
    assert config["services"]["gjallar"]["environment"]["GJALLAR_ALLOWED_ORIGINS"] == "http://127.0.0.1:8000"
    assert config["services"]["gjallar"]["environment"]["GJALLAR_ALLOW_SAME_ORIGIN"] == "true"
    assert "ports" not in config["services"]["postgres"]
    bootstrap.service("stop")
    assert bootstrap.service("start")["bind_address"] == "0.0.0.0"
    bootstrap.upgrade("gjallar:next")
    assert bootstrap.service("status")["bind_address"] == "0.0.0.0"
    assert bootstrap.load()["bind_address"] == "0.0.0.0"
    assert all(check == (8000, "0.0.0.0") for check in checks)
    assert secrets_before == {p.name: p.read_bytes() for p in (bootstrap.directory / "secrets").iterdir()}
    assert runner.admin_calls == 1


def test_invalid_bind_rejected_before_docker(setup):
    bootstrap, runner = setup
    with pytest.raises(ClientError) as error:
        bootstrap.install(bind_address="*", administrator=admin)
    assert error.value.code == "INVALID_BIND_ADDRESS"
    assert not runner.calls and not bootstrap.directory.exists()


@pytest.mark.parametrize("external", [False, True])
def test_existing_binding_change_preserves_files_and_service(setup, external):
    bootstrap, runner = setup
    options = dict(bind_address="0.0.0.0")
    bootstrap.install(administrator=admin, **(options if external else {}))
    before = bootstrap.manifest_path.read_bytes()
    config = (bootstrap.directory / "compose.json").read_bytes()
    runner.calls.clear()
    with pytest.raises(ClientError) as error:
        bootstrap.install(administrator=admin, **({} if external else options))
    assert error.value.code == "INSTALLATION_EXISTS"
    assert before == bootstrap.manifest_path.read_bytes()
    assert config == (bootstrap.directory / "compose.json").read_bytes()
    assert not any("stop" in args or "up" in args for args, _ in runner.calls)
