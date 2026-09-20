"""Explicit server-mediated registration. External mutations are never retried."""
from dataclasses import dataclass, field
import json
import os
import re
import threading
import time
from urllib.parse import quote, unquote

from app.setup_integration.contracts import SetupError, RegistrationIntent, digest
from app.setup_integration.planning import authority_warnings, build_plan, verify_token
from app.setup_integration.repository import RegistrationRepository
from app.setup_integration.transport import ProxmoxSetupTransport


@dataclass(repr=False)
class AuthenticationContext:
    actor_id: str
    session_id: str
    transport: object
    expires: float
    ticket: str = ""
    csrf: str = ""
    challenge: bool = False
    plan: dict = field(default_factory=dict)
    clock: object = time.monotonic

    def request(self, method, path, **kwargs):
        if self.expires <= self.clock() or not self.ticket:
            raise SetupError("SETUP_REAUTH_REQUIRED", "Proxmox 인증이 만료·폐기됐습니다. 다시 로그인하세요.")
        return self.transport.request(method, path, ticket=self.ticket, csrf=self.csrf, **kwargs)


class RegistrationService:
    def __init__(self, repository=None, transport_factory=ProxmoxSetupTransport, clock=time.monotonic):
        self.repository = repository or RegistrationRepository()
        self.transport_factory = transport_factory
        self.clock = clock
        self._contexts = {}
        self._attempts = {}
        self._lock = threading.Lock()

    def invalidate_session(self, session_id):
        with self._lock:
            for ctx in self._contexts.values():
                if ctx.session_id == session_id:
                    ctx.expires = 0
                    ctx.ticket = ""
                    ctx.csrf = ""
            self._contexts = {key: ctx for key, ctx in self._contexts.items() if ctx.session_id != session_id}

    def _rate_limit(self, actor_id):
        now = self.clock()
        with self._lock:
            self._contexts = {key: ctx for key, ctx in self._contexts.items() if ctx.expires > now}
            self._attempts = {key: value for key, value in self._attempts.items() if value[-1] > now - 60}
            recent = [value for value in self._attempts.get(actor_id, []) if value > now - 60]
            if len(recent) >= 5:
                raise SetupError("SETUP_LOGIN_RATE_LIMIT", "로그인 시도가 많습니다. 잠시 후 다시 시도하세요.", 429)
            self._attempts[actor_id] = [*recent, now]

    def context(self, attempt_id, actor_id, session_id, *, allow_challenge=False):
        with self._lock:
            ctx = self._contexts.get(attempt_id)
        if ctx is None or ctx.expires <= self.clock() or ctx.actor_id != actor_id or ctx.session_id != session_id:
            raise SetupError("SETUP_REAUTH_REQUIRED", "같은 Gjallar 세션에서 Proxmox에 다시 로그인하세요.")
        if ctx.challenge and not allow_challenge:
            raise SetupError("SETUP_MFA_REQUIRED", "TOTP 인증을 완료하세요.")
        return ctx

    def current(self, attempt_id, actor_id, expected_version):
        row = self.repository.get(attempt_id, actor_id)
        if row["version"] != expected_version:
            raise SetupError("SETUP_VERSION_CONFLICT", "등록 상태가 변경됐습니다. 다시 조회하세요.")
        return row

    def advance(self, row, actor_id, phase, **kwargs):
        return self.repository.advance(attempt_id=row["attempt_id"], actor_id=actor_id,
            expected_version=row["version"], expected_phases={row["phase"]}, phase=phase, **kwargs)

    def status(self, attempt_id, actor_id, session_id):
        row = self.repository.get(attempt_id, actor_id)
        try:
            self.context(attempt_id, actor_id, session_id, allow_challenge=True)
            reauth = False
        except SetupError:
            reauth = True
        return {**row, "reauth_required": reauth and not row["resolved"],
                "manual_reconciliation_required": row["phase"] in {"token_dispatching", "issue_unknown", "acl_applying", "acl_unknown", "revocation_pending"}}

    def login(self, *, attempt_id, actor_id, session_id, expected_version, password, otp=None):
        row = self.current(attempt_id, actor_id, expected_version)
        if row["resolved"] and row["phase"] != "active":
            raise SetupError("SETUP_PHASE_CONFLICT", "종료된 등록입니다.")
        if not isinstance(password, str) or not 1 <= len(password) <= 4096:
            raise SetupError("SETUP_INVALID_INPUT", "비밀번호 입력이 필요합니다.", 422)
        if otp is not None and (not isinstance(otp, str) or not re.fullmatch(r"\d{6,8}", otp)):
            raise SetupError("SETUP_INVALID_INPUT", "OTP 형식이 올바르지 않습니다.", 422)
        self._rate_limit(actor_id)
        intent = self.repository.intent(attempt_id, actor_id)
        if intent.mode != "issue":
            raise SetupError("SETUP_IMPORT_FLOW_REQUIRED", "환경변수 가져오기는 Proxmox 비밀번호 로그인을 사용하지 않습니다.")
        transport = self.transport_factory(intent.endpoint, intent.ca_pem)
        data = {"username": intent.owner, "password": password, "new-format": 1}
        if otp is not None:
            data["otp"] = otp
        result = transport.request("POST", "/access/ticket", data=data)
        ctx = self._authentication(result, intent.owner, actor_id, session_id, transport)
        with self._lock:
            self._contexts[attempt_id] = ctx
        if row["phase"] in {"prepared", "authenticated", "mfa_required", "planned"}:
            row = self.advance(row, actor_id, "mfa_required" if ctx.challenge else "authenticated")
        return {**row, "mfa_required": ctx.challenge}

    def _authentication(self, result, owner, actor_id, session_id, transport):
        if (not isinstance(result, dict) or result.get("username") != owner
                or not isinstance(result.get("ticket"), str) or not isinstance(result.get("CSRFPreventionToken"), str)):
            raise SetupError("PROXMOX_AUTH_PROTOCOL_ERROR", "Proxmox 인증 응답 형식이 올바르지 않습니다.", 502)
        ticket = result["ticket"]
        challenge = ticket.startswith("PVE:!tfa!")
        if challenge:
            try:
                value = json.loads(unquote(ticket.split(":")[1][5:]))
                if not isinstance(value, dict) or value.get("totp") is not True:
                    raise ValueError
            except (ValueError, IndexError):
                raise SetupError("PROXMOX_MFA_UNSUPPORTED", "현재 연결 절차는 pam/pve 비밀번호와 TOTP를 지원합니다.", 422) from None
        elif result.get("NeedTFA") or not ticket.startswith("PVE:"):
            raise SetupError("PROXMOX_MFA_UNSUPPORTED", "지원하지 않는 인증 응답입니다.", 422)
        return AuthenticationContext(actor_id=actor_id, session_id=session_id, transport=transport,
            expires=self.clock() + 300, ticket=ticket, csrf=result["CSRFPreventionToken"], challenge=challenge, clock=self.clock)

    def mfa(self, *, attempt_id, actor_id, session_id, expected_version, otp):
        row = self.current(attempt_id, actor_id, expected_version)
        self._rate_limit(actor_id)
        ctx = self.context(attempt_id, actor_id, session_id, allow_challenge=True)
        if not ctx.challenge or not isinstance(otp, str) or not re.fullmatch(r"\d{6,8}", otp):
            raise SetupError("SETUP_INVALID_INPUT", "진행 중인 TOTP 인증과 올바른 OTP가 필요합니다.", 422)
        intent = self.repository.intent(attempt_id, actor_id)
        result = ctx.transport.request("POST", "/access/ticket", data={"username": intent.owner,
            "tfa-challenge": ctx.ticket, "password": "totp:" + otp, "new-format": 1})
        authenticated = self._authentication(result, intent.owner, actor_id, session_id, ctx.transport)
        if authenticated.challenge:
            raise SetupError("PROXMOX_MFA_REQUIRED", "TOTP 인증이 완료되지 않았습니다.", 502)
        # MFA cannot extend the original five-minute authentication window.
        authenticated.expires = ctx.expires
        with self._lock:
            self._contexts[attempt_id] = authenticated
        if row["phase"] == "mfa_required":
            row = self.advance(row, actor_id, "authenticated")
        return row

    def plan(self, *, attempt_id, actor_id, session_id, expected_version):
        row = self.current(attempt_id, actor_id, expected_version)
        if row["phase"] not in {"authenticated", "planned"}:
            raise SetupError("SETUP_PHASE_CONFLICT", "인증 완료 후 권한 계획을 확인하세요.")
        ctx = self.context(attempt_id, actor_id, session_id)
        intent = self.repository.intent(attempt_id, actor_id)
        version = ctx.request("GET", "/version")
        if not isinstance(version, dict) or version.get("version") != "9.0.11":
            raise SetupError("PROXMOX_VERSION_UNVERIFIED", "현재 검증 대상은 pve-manager 9.0.11입니다. 다른 버전은 별도 검증이 필요합니다.", 422)
        if not time.time() + 300 < intent.expires_at <= time.time() + 90 * 86400:
            raise SetupError("SETUP_EXPIRY_INVALID", "token 만료를 현재부터 5분 초과·90일 이내로 설정하세요.", 422)
        owner = ctx.request("GET", "/access/users/" + quote(intent.owner, safe=""))
        if (not isinstance(owner, dict) or owner.get("enable", 1) not in {1, True}
                or (owner.get("expire", 0) and intent.expires_at > owner["expire"])):
            raise SetupError("PROXMOX_OWNER_UNAVAILABLE", "계정 활성 상태와 만료일을 확인하세요.", 422)
        plan = build_plan(intent, ctx.request, attempt_id=attempt_id, connection_version=row["connection_version"])
        ctx.plan = plan
        row = self.advance(row, actor_id, "planned", plan_digest=plan["digest"])
        return {**row, "plan": plan}

    @staticmethod
    def token_path(intent, attempt_id):
        return "/access/users/" + quote(intent.owner, safe="") + "/token/gjallar-" + attempt_id

    def tokens(self, intent, ctx):
        result = ctx.request("GET", "/access/users/" + quote(intent.owner, safe="") + "/token")
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise SetupError("PROXMOX_PROTOCOL_ERROR", "token 목록 형식이 올바르지 않습니다.", 502)
        return result

    def confirm(self, *, attempt_id, actor_id, session_id, expected_version, plan_digest):
        row = self.current(attempt_id, actor_id, expected_version)
        if row["phase"] != "planned":
            raise SetupError("SETUP_PHASE_CONFLICT", "확인할 권한 계획이 없습니다.")
        ctx = self.context(attempt_id, actor_id, session_id)
        plan = ctx.plan
        if not plan or not plan["can_confirm"] or plan["digest"] != plan_digest or row["plan_digest"] != plan_digest:
            raise SetupError("SETUP_PLAN_CONFLICT", "권한 계획을 다시 조회하고 확인하세요.")
        intent = self.repository.intent(attempt_id, actor_id)
        refreshed = build_plan(intent, ctx.request, attempt_id=attempt_id, connection_version=row["connection_version"])
        if refreshed["digest"] != plan_digest or not refreshed["can_confirm"] or intent.expires_at <= time.time() + 300:
            raise SetupError("SETUP_PLAN_CONFLICT", "실행 전 권한 또는 만료 조건이 변경됐습니다. 계획을 다시 확인하세요.")
        if any(item.get("tokenid") == "gjallar-" + attempt_id for item in self.tokens(intent, ctx)):
            raise SetupError("PROXMOX_TOKEN_COLLISION", "이미 존재하는 token ID입니다. 기존 token을 변경하지 않습니다.")
        # The durable marker precedes every external change. Any failure after
        # this point requires observation, never automatic issue/ACL retries.
        row = self.advance(row, actor_id, "token_dispatching", operation_status="dispatching")
        result = ctx.request("POST", self.token_path(intent, attempt_id), data={"privsep": 1,
            "expire": intent.expires_at, "comment": "Gjallar registration " + attempt_id})
        if (not isinstance(result, dict) or result.get("full-tokenid") != plan["token_id"]
                or not isinstance(result.get("value"), str) or not result["value"]):
            raise SetupError("PROXMOX_ISSUE_UNKNOWN", "발급 결과를 확인할 수 없습니다. 등록 상태에서 exact token을 관찰하세요.", 502)
        row = self.repository.stage_secret(attempt_id=attempt_id, actor_id=actor_id, expected_version=row["version"],
            token_secret=result["value"], token_id=plan["token_id"])
        del result
        row = self.advance(row, actor_id, "acl_applying")
        for name in plan["create_roles"]:
            ctx.request("POST", "/access/roles", data={"roleid": name, "privs": " ".join(plan["roles"][name])})
        for acl in plan["acls"]:
            ctx.request("PUT", "/access/acl", data={"path": acl["path"], "roles": acl["role"],
                "propagate": acl["propagate"], "tokens": plan["token_id"]})
        row = self.advance(row, actor_id, "verifying", operation_status="verifying")
        return self.verify(attempt_id=attempt_id, actor_id=actor_id, expected_version=row["version"])

    def verify(self, *, attempt_id, actor_id, expected_version):
        row = self.current(attempt_id, actor_id, expected_version)
        if row["phase"] not in {"secret_staged", "verifying", "verification_failed", "acl_applying", "acl_unknown", "verified"}:
            raise SetupError("SETUP_PHASE_CONFLICT", "현재 상태에서 token을 검증할 수 없습니다.")
        intent = self.repository.intent(attempt_id, actor_id)
        configuration, secret = self.repository.pending_credential(attempt_id=attempt_id, actor_id=actor_id)
        transport = self.transport_factory(intent.endpoint, intent.ca_pem)
        def request(method, path, **kwargs):
            return transport.request(method, path, token_id=configuration["token_id"], secret=secret, **kwargs)
        observed = verify_token(intent, request)
        if row["phase"] in {"secret_staged", "acl_applying", "acl_unknown"}:
            row = self.advance(row, actor_id, "verifying", operation_status="verifying")
        row = self.advance(row, actor_id, "verified")
        return {**row, "observed_scope": observed}

    def observe(self, *, attempt_id, actor_id, session_id, expected_version):
        row = self.current(attempt_id, actor_id, expected_version)
        ctx = self.context(attempt_id, actor_id, session_id)
        intent = self.repository.intent(attempt_id, actor_id)
        matches = [value for value in self.tokens(intent, ctx) if value.get("tokenid") == "gjallar-" + attempt_id]
        exists = bool(matches)
        # Even observed absence does not prove an earlier request has finished.
        return {**row, "token_exists": exists,
                "token_matches_attempt": exists and matches[0].get("comment") == "Gjallar registration " + attempt_id,
                "secret_recoverable": row["revision_id"] is not None,
                "automatic_retry_allowed": False}

    def activate(self, *, attempt_id, actor_id, expected_version):
        row = self.verify(attempt_id=attempt_id, actor_id=actor_id, expected_version=expected_version)
        result = self.repository.activate(attempt_id=attempt_id, actor_id=actor_id, expected_version=row["version"])
        with self._lock:
            self._contexts.pop(attempt_id, None)
        return result

    def cancel(self, *, attempt_id, actor_id, expected_version):
        row = self.current(attempt_id, actor_id, expected_version)
        if row["phase"] not in {"prepared", "authenticated", "mfa_required", "planned"}:
            raise SetupError("SETUP_CLEANUP_REQUIRED", "발급 시도 후에는 취소로 token을 없앨 수 없습니다. exact token을 확인·폐기하세요.")
        result = self.advance(row, actor_id, "cancelled", operation_status="cancelled", resolved=True)
        with self._lock:
            self._contexts.pop(attempt_id, None)
        return result

    def revoke(self, *, attempt_id, actor_id, session_id, expected_version, token_id):
        row = self.current(attempt_id, actor_id, expected_version)
        ctx = self.context(attempt_id, actor_id, session_id)
        intent = self.repository.intent(attempt_id, actor_id)
        if token_id != intent.owner + "!gjallar-" + attempt_id:
            raise SetupError("SETUP_TOKEN_ID_CONFLICT", "폐기할 exact token ID를 확인하세요.")
        matches = [value for value in self.tokens(intent, ctx) if value.get("tokenid") == "gjallar-" + attempt_id]
        if row["phase"] == "revocation_pending":
            if matches:
                raise SetupError("SETUP_REVOCATION_PENDING", "이전 폐기 요청의 결과가 아직 확인되지 않았습니다. 자동으로 다시 폐기하지 않습니다.")
            return self.repository.finish_revoke(attempt_id=attempt_id, actor_id=actor_id, expected_version=row["version"])
        if len(matches) != 1 or matches[0].get("comment") != "Gjallar registration " + attempt_id:
            raise SetupError("SETUP_TOKEN_OWNERSHIP_UNKNOWN", "이 등록에서 발급한 token인지 확인되지 않습니다. 수동 확인이 필요합니다.")
        row = self.repository.begin_revoke(attempt_id=attempt_id, actor_id=actor_id, expected_version=row["version"])
        ctx.request("DELETE", self.token_path(intent, attempt_id))
        if any(value.get("tokenid") == "gjallar-" + attempt_id for value in self.tokens(intent, ctx)):
            raise SetupError("SETUP_REVOCATION_PENDING", "token 부재를 확인하지 못했습니다.")
        result = self.repository.finish_revoke(attempt_id=attempt_id, actor_id=actor_id, expected_version=row["version"])
        with self._lock:
            self._contexts.pop(attempt_id, None)
        return result

    def env_credential(self, intent):
        endpoint = os.getenv("PROXMOX_API_URL", "")
        token_id = os.getenv("PROXMOX_API_TOKEN_ID", "")
        secret = os.getenv("PROXMOX_API_TOKEN_SECRET", "")
        if (not endpoint or not secret or not re.fullmatch(re.escape(intent.owner) + r"![A-Za-z0-9_.-]+", token_id)
                or os.getenv("PROXMOX_TLS_INSECURE", "").lower() in {"1", "true", "yes", "on"}):
            raise SetupError("SETUP_ENV_IMPORT_UNAVAILABLE", "기존 env 연결과 TLS 검증 설정을 확인하세요. insecure 연결은 가져오지 않습니다.", 422)
        try:
            normalized = RegistrationIntent.endpoint_origin(endpoint)
        except ValueError:
            raise SetupError("SETUP_ENV_IMPORT_UNAVAILABLE", "기존 env endpoint가 HTTPS 등록 정책과 맞지 않습니다.", 422) from None
        if normalized != intent.endpoint:
            raise SetupError("SETUP_ENV_IMPORT_CONFLICT", "가져올 기존 endpoint가 입력한 대상과 다릅니다.")
        return token_id, secret

    def import_plan(self, *, attempt_id, actor_id, expected_version):
        row = self.current(attempt_id, actor_id, expected_version)
        intent = self.repository.intent(attempt_id, actor_id)
        if intent.mode != "import_env" or row["phase"] not in {"prepared", "planned"}:
            raise SetupError("SETUP_PHASE_CONFLICT", "환경변수 가져오기 등록이 아닙니다.")
        token_id, _ = self.env_credential(intent)
        plan = {"endpoint": intent.endpoint, "token_id": token_id, "scope": intent.scope.model_dump(),
                "features": intent.features, "connection_version": row["connection_version"],
                "trust_digest": digest(intent.ca_pem), "mode": "import_env", "upstream_changes": False,
                "expires_at": None, "can_confirm": True, "roles": {}, "create_roles": [], "acls": [],
                "authority_warnings": authority_warnings(intent)}
        row = self.advance(row, actor_id, "planned", plan_digest=digest(plan))
        return {**row, "plan": {**plan, "digest": row["plan_digest"]}}

    def import_env(self, *, attempt_id, actor_id, expected_version, plan_digest):
        row = self.current(attempt_id, actor_id, expected_version)
        intent = self.repository.intent(attempt_id, actor_id)
        if intent.mode != "import_env" or row["phase"] not in {"planned", "import_staging"} or row["plan_digest"] != plan_digest:
            raise SetupError("SETUP_PLAN_CONFLICT", "가져오기 계획을 다시 확인하세요.")
        token_id, secret = self.env_credential(intent)
        plan = {"endpoint": intent.endpoint, "token_id": token_id, "scope": intent.scope.model_dump(),
                "features": intent.features, "connection_version": row["connection_version"],
                "trust_digest": digest(intent.ca_pem), "mode": "import_env", "upstream_changes": False,
                "expires_at": None, "can_confirm": True, "roles": {}, "create_roles": [], "acls": [],
                "authority_warnings": authority_warnings(intent)}
        if digest(plan) != plan_digest:
            raise SetupError("SETUP_PLAN_CONFLICT", "기존 연결이 변경됐습니다. 계획을 다시 확인하세요.")
        transport = self.transport_factory(intent.endpoint, intent.ca_pem)
        verify_token(intent, lambda method, path, **kwargs: transport.request(method, path,
            token_id=token_id, secret=secret, **kwargs))
        if row["phase"] == "planned":
            row = self.advance(row, actor_id, "import_staging", operation_status="dispatching")
        row = self.repository.stage_secret(attempt_id=attempt_id, actor_id=actor_id, expected_version=row["version"],
            token_secret=secret, token_id=token_id)
        row = self.advance(row, actor_id, "verifying", operation_status="verifying")
        return self.advance(row, actor_id, "verified")


service = RegistrationService()
