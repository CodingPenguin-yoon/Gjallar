"""Guided managed Compose deployment. No arbitrary shell or implicit migration."""
from contextlib import contextmanager
from importlib.resources import files
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import uuid

from .connections import atomic_json, file_lock, private_directory
from .errors import ClientError

IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
ARCHITECTURES = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}


class Docker:
    def __init__(self):
        self.executable = shutil.which("docker")

    def __call__(self, args, *, input_text=None):
        if not self.executable:
            raise ClientError("DOCKER_MISSING", "Docker가 없습니다. https://docs.docker.com/get-started/get-docker/ 에서 OS별 Docker·Compose 설치 후 다시 실행하세요. 호스트 설정은 변경하지 않았습니다.", 2)
        # Do not inherit application/database secrets, COMPOSE_FILE or project overrides.
        env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "DOCKER_CONFIG") if key in os.environ}
        try:
            result = subprocess.run([self.executable, *args], input=input_text, capture_output=True,
                                    text=True, timeout=300, check=False, env=env)
        except (OSError, subprocess.TimeoutExpired):
            raise ClientError("DOCKER_UNAVAILABLE", "Docker 실행 실패·시간 초과입니다. 현재 상태를 확인한 뒤 같은 설치 경로로 재실행하세요.") from None
        if result.returncode:
            # Compose/engine errors can include environment, SQL or secret input.
            raise ClientError("DOCKER_FAILED", "Docker 작업이 실패했습니다. Docker·Compose·이미지·서비스 상태를 확인하세요. 기존 설정·volume은 보존했습니다.")
        return result.stdout


def check_port(port):
    if not 1024 <= port <= 65535:
        raise ClientError("INVALID_PORT", "port는 1024~65535 범위여야 합니다.", 2)
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise ClientError("PORT_IN_USE", "선택한 loopback port가 사용 중입니다. 다른 port를 선택하세요.", 2) from None


def parse_json(value):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        raise ClientError("DOCKER_PROTOCOL", "Docker 응답을 확인할 수 없습니다.") from None


def compose_config(manifest):
    identity = manifest["id"]
    credential_secrets = ["credential_key"] if manifest["version"] >= 2 else []
    common = {
        "image": manifest["image"],
        "entrypoint": ["python", "-m", "app.installation.maintenance"],
        "environment": {
            "GJALLAR_DATABASE_URL_FILE": "/run/secrets/database_url",
            "GJALLAR_INSTALLATION_ID": identity,
            **({"GJALLAR_CREDENTIAL_KEY_FILE": "/run/secrets/credential_key"} if credential_secrets else {}),
            "GJALLAR_ALLOWED_ORIGINS": f'http://127.0.0.1:{manifest["port"]}',
            "GJALLAR_SESSION_COOKIE_SECURE": "false",
            "GJALLAR_SESSION_COOKIE_SAMESITE": "lax",
            "GJALLAR_INVENTORY_MODE": "live",
        },
        "secrets": ["database_url", *credential_secrets],
        "depends_on": {"postgres": {"condition": "service_healthy"}},
        "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
    }
    return {
        "services": {
            "postgres": {
                "image": manifest["postgres_image"], "restart": "unless-stopped",
                "environment": {"POSTGRES_USER": "postgres", "POSTGRES_DB": "gjallar", "POSTGRES_PASSWORD_FILE": "/run/gjallar/postgres_password"},
                "entrypoint": ["sh", "/opt/gjallar/postgres-entrypoint.sh"],
                "command": ["postgres"], "tmpfs": ["/run/gjallar"],
                "secrets": ["postgres_password", "app_password"],
                "volumes": ["pgdata:/var/lib/postgresql/data", "./init-postgres.sh:/docker-entrypoint-initdb.d/10-gjallar.sh:ro", "./postgres-entrypoint.sh:/opt/gjallar/postgres-entrypoint.sh:ro"],
                "healthcheck": {"test": ["CMD", "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "postgres"], "interval": "2s", "timeout": "5s", "retries": 30},
                "logging": common["logging"],
            },
            "maintenance": {**common, "profiles": ["maintenance"], "command": ["status"]},
            "gjallar": {**common, "entrypoint": ["python", "-m", "app.installation.serve"],
                        "restart": "unless-stopped", "ports": [f'127.0.0.1:{manifest["port"]}:8000'],
                        "healthcheck": {"test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"],
                                        "interval": "3s", "timeout": "5s", "retries": 30}},
        },
        "volumes": {"pgdata": {"external": True, "name": manifest["volume"]}},
        "secrets": {name: {"file": f"./secrets/{name}"} for name in ("database_url", "postgres_password", "app_password", *credential_secrets)},
    }


class Bootstrap:
    def __init__(self, directory: Path, runner=None, port_check=check_port):
        self.directory = directory.expanduser().absolute()
        self.runner = runner or Docker()
        self.port_check = port_check
        self.manifest_path = self.directory / "installation.json"

    @contextmanager
    def locked(self):
        private_directory(self.directory)
        with file_lock(self.directory / ".installation.lock"):
            yield

    def preflight(self):
        if platform.system() not in {"Linux", "Darwin"} or platform.machine().lower() not in {"arm64", "aarch64", "x86_64", "amd64"}:
            raise ClientError("UNSUPPORTED_PLATFORM", "이번 설치 대상은 Linux/macOS의 amd64·arm64입니다. 실제 OS별 검증 완료 여부는 개발 안내를 확인하세요.", 2)
        version = self.runner(["compose", "version", "--short"]).strip().lstrip("v")
        match = re.match(r"(\d+)\.(\d+)", version)
        if not match or tuple(map(int, match.groups())) < (2, 20):
            raise ClientError("COMPOSE_VERSION", "Docker Compose 2.20 이상이 필요합니다.", 2)
        endpoint = self.runner(["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"] ).strip()
        if not endpoint.startswith("unix://"):
            raise ClientError("REMOTE_DOCKER_REJECTED", "로컬 Unix socket Docker context만 허용합니다. 원격 Docker에는 설치하지 않습니다.", 2)
        info = parse_json(self.runner(["info", "--format", "{{json .}}"] ))
        if not isinstance(info, dict) or info.get("OSType") != "linux" or info.get("Architecture") not in {"aarch64", "arm64", "x86_64", "amd64"}:
            raise ClientError("DOCKER_PLATFORM", "Linux amd64/arm64 Docker engine이 필요합니다.", 2)
        self.engine_architecture = ARCHITECTURES[info["Architecture"]]

    def image(self, reference, *, pull=False):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:-]{0,255}", reference):
            raise ClientError("INVALID_IMAGE", "이미지 참조가 올바르지 않습니다.", 2)
        if pull:
            self.runner(["pull", reference])
        result = parse_json(self.runner(["image", "inspect", reference, "--format", "{{json .}}"] ))
        if not isinstance(result, dict):
            raise ClientError("DOCKER_PROTOCOL", "이미지 정보를 확인할 수 없습니다.")
        image_id = result.get("Id")
        if (not isinstance(image_id, str) or not IMAGE_ID.fullmatch(image_id) or result.get("Os") != "linux"
                or ARCHITECTURES.get(result.get("Architecture")) != self.engine_architecture):
            raise ClientError("INVALID_IMAGE", "검증할 수 없는 이미지입니다.", 2)
        # Containerd image stores can drop an untagged index after its source tag moves.
        # Keep a content-named reference; manifests still use the verified immutable ID.
        self.runner(["image", "tag", image_id, "gjallar-pinned:" + image_id.replace(":", "-")])
        return image_id

    @staticmethod
    def validate_manifest(data):
        if set(data) != {"version", "id", "project", "volume", "port", "image", "postgres_image", "state"} or data["version"] not in {1, 2}:
            raise ValueError
        uid = str(uuid.UUID(data["id"]))
        if data["project"] != "gjallar-" + uid or data["volume"] != "gjallar-" + uid + "-pgdata":
            raise ValueError
        if type(data["port"]) is not int or not 1024 <= data["port"] <= 65535:
            raise ValueError
        if not all(IMAGE_ID.fullmatch(data[key]) for key in ("image", "postgres_image")):
            raise ValueError
        if data["state"] not in {"preparing", "prepared", "storage_ready", "ready"}:
            raise ValueError
        return data

    def load(self):
        try:
            if self.manifest_path.is_symlink():
                raise ValueError
            return self.validate_manifest(json.loads(self.manifest_path.read_text()))
        except (OSError, TypeError, ValueError, KeyError):
            raise ClientError("INSTALLATION_INVALID", "기존 설치 manifest가 손상되었거나 없습니다. 덮어쓰지 않고 중단합니다.") from None

    def volumes(self):
        return self.runner(["volume", "ls", "--format", "{{.Name}}"] ).splitlines()

    def volume(self, manifest, *, create=False):
        name = manifest["volume"]
        if name not in self.volumes():
            if not create:
                raise ClientError("VOLUME_MISSING", "기존 DB volume이 없습니다. 새 DB를 만들지 않고 중단합니다.")
            self.runner(["volume", "create", "--label", f'org.gjallar.installation={manifest["id"]}', name])
        info = parse_json(self.runner(["volume", "inspect", name, "--format", "{{json .}}"] ))
        if not isinstance(info, dict) or not isinstance(info.get("Labels"), dict) or info["Labels"].get("org.gjallar.installation") != manifest["id"]:
            raise ClientError("VOLUME_CONFLICT", "다른 설치의 volume입니다. 변경하지 않습니다.")

    def _secret(self, name, value):
        path = self.directory / "secrets" / name
        if path.exists():
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise ClientError("SECRET_UNSAFE", "전용 secret 파일의 권한 또는 경로를 확인하세요.")
            return path.read_text()
        fd, pending = tempfile.mkstemp(prefix=".secret-pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(pending, path)  # Atomic creation; never replace an existing secret.
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            os.unlink(pending)
        return value

    def prepare_files(self, manifest):
        private_directory(self.directory / "secrets")
        postgres_password = self._secret("postgres_password", secrets.token_hex(32))
        app_password = self._secret("app_password", secrets.token_hex(32))
        values = [postgres_password, app_password]
        if manifest["version"] >= 2:
            values.append(self._secret("credential_key", secrets.token_hex(32)))
        if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in values):
            raise ClientError("SECRET_INVALID", "중단된 secret 파일이 손상되었습니다. 값을 덮어쓰지 않고 중단합니다.")
        database_url = f"postgresql+psycopg://gjallar:{app_password}@postgres:5432/gjallar"
        if self._secret("database_url", database_url) != database_url:
            raise ClientError("SECRET_CONFLICT", "DB credential 파일들이 일치하지 않습니다.")
        for name in ("init-postgres.sh", "postgres-entrypoint.sh"):
            script = self.directory / name
            expected = files("gjallar_client").joinpath("assets/" + name).read_text()
            if script.is_symlink() or (script.exists() and script.read_text() != expected):
                raise ClientError("CONFIG_CONFLICT", "기존 DB 준비 script가 변경되었습니다. 보존하고 중단합니다.")
            if not script.exists():
                script.write_text(expected)
                # Scripts contain no credentials; postgres must read the init script.
                script.chmod(0o644)
        compose = self.directory / "compose.json"
        if compose.exists() and parse_json(compose.read_text()) != compose_config(manifest):
            raise ClientError("CONFIG_CONFLICT", "기존 Compose 설정이 다릅니다. 보존하고 중단합니다.")
        atomic_json(compose, compose_config(manifest))
        manifest["state"] = "prepared"
        atomic_json(self.manifest_path, manifest)

    def validate_files(self, manifest):
        directory = self.directory / "secrets"
        if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o077 or directory.stat().st_uid != os.getuid():
            raise ClientError("SECRET_UNSAFE", "secret 디렉터리는 현재 사용자 소유의 0700 경로여야 합니다.")
        names = ("postgres_password", "app_password", "database_url") + (("credential_key",) if manifest["version"] >= 2 else ())
        for name in names:
            path = self.directory / "secrets" / name
            if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid() or not path.read_text():
                raise ClientError("SECRET_MISSING", "기존 secret이 없거나 권한이 올바르지 않습니다. 재생성하지 않습니다.")
        path = self.directory / "compose.json"
        if path.is_symlink() or parse_json(path.read_text()) != compose_config(manifest):
            raise ClientError("CONFIG_CONFLICT", "Compose 설정이 manifest와 다릅니다. 기존 파일을 보존합니다.")
        for name in ("init-postgres.sh", "postgres-entrypoint.sh"):
            script = self.directory / name
            if script.is_symlink() or script.read_text() != files("gjallar_client").joinpath("assets/" + name).read_text():
                raise ClientError("CONFIG_CONFLICT", "DB 준비 script가 변경되었습니다.")

    def compose(self, manifest, args, *, input_text=None):
        return self.runner(["compose", "--project-directory", str(self.directory), "--project-name", manifest["project"],
                            "--env-file", "/dev/null", "-f", str(self.directory / "compose.json"), *args], input_text=input_text)

    def maintenance(self, manifest, command, payload=None):
        output = self.compose(manifest, ["run", "--rm", "--no-deps", "-T", "maintenance", command],
                              input_text=json.dumps(payload) if payload is not None else None)
        result = parse_json(output)
        if not isinstance(result, dict) or result.get("ok") is not True or result.get("state") not in {"initializing", "schema_ready", "ready", "created", "already_initialized"}:
            raise ClientError("INITIALIZATION_FAILED", "서버 초기화가 거부되었습니다. 기존 DB·계정·revision을 보존하고 상태를 확인하세요.")
        return result["state"]

    def install(self, *, image=None, port=8000, administrator=None):
        self.preflight()
        with self.locked():
            self.recover_upgrade()
            if self.manifest_path.exists():
                manifest = self.load()
                if image and self.image(image) != manifest["image"]:
                    raise ClientError("UPGRADE_REQUIRED", "기존 설치 이미지 변경은 upgrade --image로 명시하세요.", 2)
                if manifest["port"] != port:
                    raise ClientError("INSTALLATION_EXISTS", "기존 port를 보존합니다. 기존 설치 port로 재실행하세요.", 2)
                # Never change an existing install image implicitly.
                if manifest["state"] == "ready":
                    return self._start(manifest)
            else:
                unknown = set(p.name for p in self.directory.iterdir()) - {".installation.lock"}
                if unknown:
                    raise ClientError("PATH_NOT_EMPTY", "설치 경로에 기존 파일이 있습니다. 덮어쓰지 않습니다.", 2)
                self.port_check(port)
                uid = str(uuid.uuid4())
                manifest = {"version": 2, "id": uid, "project": "gjallar-" + uid, "volume": "gjallar-" + uid + "-pgdata",
                            "port": port, "image": self.image(image or "gjallar:local"), "postgres_image": self.image("postgres:17-bookworm", pull=True), "state": "preparing"}
                if manifest["volume"] in self.volumes():
                    raise ClientError("VOLUME_CONFLICT", "새 설치 이름의 volume이 이미 존재합니다.")
                atomic_json(self.manifest_path, manifest)
            if manifest["state"] == "preparing":
                if manifest["volume"] in self.volumes():
                    raise ClientError("VOLUME_CONFLICT", "파일 준비 미완료인데 volume이 존재합니다. 자동 초기화하지 않습니다.")
                self.prepare_files(manifest)
            self.validate_files(manifest)
            self.volume(manifest, create=manifest["state"] == "prepared")
            if manifest["state"] == "prepared":
                # Persist before any DB process can write rows into this volume.
                manifest["state"] = "storage_ready"
                atomic_json(self.manifest_path, manifest)
            self.compose(manifest, ["up", "-d", "--wait", "--wait-timeout", "120", "postgres"])
            if manifest["state"] == "storage_ready":
                # Retry only this fresh, not-yet-ready installation's DB role setup.
                self.compose(manifest, ["exec", "-T", "--user", "postgres", "postgres", "sh", "/docker-entrypoint-initdb.d/10-gjallar.sh"])
            self.maintenance(manifest, "init-schema")
            state = self.maintenance(manifest, "status")
            if state != "ready":
                if administrator is None:
                    raise ClientError("ADMIN_REQUIRED", "최초 관리자 입력이 필요합니다. 같은 설치 경로로 다시 실행하세요.", 2)
                payload = administrator()
                try:
                    self.maintenance(manifest, "setup-admin", payload)
                finally:
                    payload.clear()
            self.maintenance(manifest, "check-ready")
            manifest["state"] = "ready"
            atomic_json(self.manifest_path, manifest)
            return self._start(manifest)

    def _start(self, manifest):
        self.validate_files(manifest)
        self.volume(manifest)
        if manifest["state"] != "ready":
            raise ClientError("INITIALIZATION_INCOMPLETE", "초기화 미완료입니다. bootstrap을 같은 경로로 재실행하세요.")
        # Running port belongs to this project only if Compose reports it running.
        running = self.compose(manifest, ["ps", "--status", "running", "--services"]).splitlines()
        if "gjallar" not in running:
            self.port_check(manifest["port"])
        self.compose(manifest, ["up", "-d", "--wait", "--wait-timeout", "120", "postgres"])
        self.maintenance(manifest, "check-ready")
        self.compose(manifest, ["up", "-d", "--wait", "--wait-timeout", "120", "gjallar"])
        return {"ok": True, "state": "running", "url": f'http://127.0.0.1:{manifest["port"]}',
                "message": "설치 시 만든 Gjallar 계정으로 로그인하세요. Proxmox 연결은 로그인 후 별도로 등록·확인합니다. TUI 종료는 서비스를 중지하지 않습니다."}

    def service(self, action):
        self.preflight()
        with self.locked():
            if action == "start":
                self.recover_upgrade()
            elif action == "stop":
                self.recover_upgrade(start=False)
            elif (self.directory / "upgrade.json").exists():
                if action == "status":
                    return {"ok": False, "exit_code": 7, "state": "upgrade_pending", "message": "중단된 업그레이드가 있습니다. service start로 검증된 전환을 재개하세요. 이전 설정은 before-upgrade 디렉터리에 보존됩니다."}
            manifest = self.load()
            self.validate_files(manifest)
            self.volume(manifest)
            if action == "start":
                return self._start(manifest)
            if action == "stop":
                self.compose(manifest, ["stop", "gjallar"])
                self.compose(manifest, ["stop", "postgres"])
                return {"ok": True, "state": "stopped", "message": "서비스만 중지했습니다. DB·계정·작업 기록·volume은 보존됩니다."}
            if action == "status":
                output = self.compose(manifest, ["ps", "--all", "--format", "json"])
                # Compose v2 versions emit either one JSON array or JSON lines.
                text = output.strip()
                rows = parse_json(text) if text.startswith("[") else [parse_json(line) for line in text.splitlines()]
                return {"ok": True, "installation_state": manifest["state"], "services": [
                    {key: row.get(key) for key in ("Service", "State", "Health")} for row in rows],
                    "url": f'http://127.0.0.1:{manifest["port"]}'}
            raise ClientError("INVALID_ACTION", "start/status/stop 중 하나를 사용하세요.", 2)

    def upgrade(self, image):
        self.preflight()
        with self.locked():
            self.recover_upgrade()
            manifest = self.load()
            self.validate_files(manifest)
            self.volume(manifest)
            candidate = {**manifest, "image": self.image(image)}
            # Check target schema/identity before stopping the current application.
            # No migration here: a schema-changing upgrade needs separate approval.
            running = self.compose(manifest, ["ps", "--status", "running", "--services"]).splitlines()
            if "gjallar" in running:
                self.compose(manifest, ["exec", "-T", "gjallar", "python", "-m", "app.installation.maintenance", "check-ready"])
            else:
                self.compose(manifest, ["run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "maintenance",
                                        "-m", "app.installation.maintenance", "check-ready"])
            if candidate["image"] == manifest["image"]:
                return {"ok": True, "state": "unchanged"}
            # Use a candidate compose file, never overwrite active config before validation.
            candidate_path = self.directory / "upgrade-candidate.json"
            atomic_json(candidate_path, compose_config(candidate))
            args = ["compose", "--project-directory", str(self.directory), "--project-name", manifest["project"],
                    "--env-file", "/dev/null", "-f", str(candidate_path)]
            self.runner([*args, "run", "--rm", "--no-deps", "-T", "maintenance", "check-ready"])
            # Save explicit rollback files; never replace their prior versions.
            backup = self.directory / ("before-upgrade-" + uuid.uuid4().hex)
            backup.mkdir(mode=0o700)
            atomic_json(backup / "installation.json", manifest)
            atomic_json(backup / "compose.json", compose_config(manifest))
            self.compose(manifest, ["stop", "gjallar"])
            atomic_json(self.directory / "upgrade.json", {"before": manifest, "candidate": candidate})
            atomic_json(self.directory / "compose.json", compose_config(candidate))
            atomic_json(self.manifest_path, candidate)
            result = self._start(candidate)
            (self.directory / "upgrade.json").unlink()
            return result

    def recover_upgrade(self, *, start=True):
        journal = self.directory / "upgrade.json"
        if not journal.exists():
            return
        try:
            if journal.is_symlink():
                raise ValueError
            data = json.loads(journal.read_text())
            before = self.validate_manifest(data["before"])
            candidate = self.validate_manifest(data["candidate"])
            if {k: v for k, v in before.items() if k != "image"} != {k: v for k, v in candidate.items() if k != "image"}:
                raise ValueError
            if self.load() not in (before, candidate):
                raise ValueError
            current = parse_json((self.directory / "compose.json").read_text())
            if current not in (compose_config(before), compose_config(candidate)):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise ClientError("UPGRADE_CONFLICT", "업그레이드 기록과 파일이 일치하지 않습니다. 보존된 설정으로 수동 복구하세요.") from None
        self.volume(candidate)
        atomic_json(self.directory / "compose.json", compose_config(candidate))
        atomic_json(self.manifest_path, candidate)
        # Readiness is still checked by _start; journal remains until that succeeds.
        self.validate_files(candidate)
        if start:
            self._start(candidate)
            journal.unlink()
