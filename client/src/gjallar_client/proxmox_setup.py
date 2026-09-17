"""Shared interactive registration for CLI and the minimal menu TUI."""
import json
from pathlib import Path
import time
import uuid

from .errors import ClientError


def wizard(app, *, read, password, output, attempt_id=None):
    if attempt_id:
        row = app.proxmox_setup("status", attempt_id=attempt_id)["data"]
    else:
        mode = "import_env" if read("서버의 기존 env token을 가져올까요? [yes/새 토큰 발급]: ").strip() == "yes" else "issue"
        endpoint = read("Proxmox HTTPS 주소: ").strip()
        owner = read("Proxmox 계정 (예: user@pam 또는 user@pve): ").strip()
        ca_path = read("공개 CA PEM 파일 (system CA는 Enter): ").strip()
        ca_pem = Path(ca_path).read_text() if ca_path else ""
        nodes = [value.strip() for value in read("조회할 노드 이름 (쉼표 구분): ").split(",") if value.strip()]
        try:
            vmids = [int(value.strip()) for value in read("조회할 VM/template ID (쉼표 구분, 없으면 Enter): ").split(",") if value.strip()]
        except ValueError:
            raise ClientError("INVALID_VMID", "VMID는 숫자로 입력하세요.", 2) from None
        storages = [value.strip() for value in read("조회할 storage ID (쉼표 구분, 없으면 Enter): ").split(",") if value.strip()]
        bridges = [value.strip() for value in read("조회할 bridge (쉼표 구분, 없으면 Enter): ").split(",") if value.strip()]
        features = ["read"]
        if read("선택한 VM의 시작·정상 종료 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("power")
        row = app.proxmox_setup("prepare", body={"idempotency_key": str(uuid.uuid4()), "intent": {
            "endpoint": endpoint, "owner": owner, "ca_pem": ca_pem,
            "scope": {"nodes": nodes, "vmids": vmids, "storages": storages, "bridges": bridges},
            "features": features, "expires_at": int(time.time()) + 30 * 86400,
            "mode": mode,
        }})["data"]
    output("등록 ID: " + row["attempt_id"] + " · 중단 후 이 ID로 상태를 확인할 수 있습니다.")
    def step(action, **kwargs):
        return app.proxmox_setup(action, attempt_id=row["attempt_id"], body={"expected_version": row["version"], **kwargs})["data"]
    def authenticate():
        current = row
        otp = password("realm OTP (미사용은 Enter): ") or None
        current = step("login", password=password("Proxmox 비밀번호: "), **({"otp": otp} if otp else {}))
        if current.get("mfa_required"):
            current = app.proxmox_setup("mfa", attempt_id=current["attempt_id"], body={
                "expected_version": current["version"], "otp": password("TOTP: ")})["data"]
        return current
    if row["phase"] in {"cancelled", "revoked"}:
        return {"ok": True, "data": row, "message": "종료된 등록입니다. 새 연결은 --resume 없이 시작하세요."}
    cleanup_phases = {"token_dispatching", "issue_unknown", "secret_staged", "acl_applying", "acl_unknown", "verified", "active", "revocation_pending"}
    if attempt_id and row.get("mode") != "import_env" and row["phase"] in cleanup_phases:
        choice = read("등록 토큰 확인·폐기 [observe/revoke/Enter=계속]: ").strip()
        if choice in {"observe", "revoke"}:
            row = authenticate()
            row = step("observe")
            output(json.dumps(row, ensure_ascii=True, indent=2))
            if choice == "revoke":
                output("활성 토큰을 폐기하면 조회·조작이 중단됩니다. 미확정 폐기 요청은 재전송하지 않고 결과만 확인합니다.")
                token_id = read("폐기·결과 확인할 전체 토큰 ID (취소는 Enter): ").strip()
                if token_id:
                    row = step("revoke", token_id=token_id)
            return {"ok": True, "data": row}
    if row["phase"] == "active":
        return {"ok": True, "data": row, "message": "연결이 저장됐습니다. 모든 서버 프로세스 재시작 후 자원 조회를 확인하세요."}
    if row["phase"] in {"secret_staged", "verifying", "acl_applying", "acl_unknown", "verified"}:
        row = step("verify")
    elif row.get("mode") == "import_env" and row["phase"] in {"prepared", "planned", "import_staging"}:
        if row["phase"] != "import_staging":
            row = step("import-plan")
            output(json.dumps(row["plan"], ensure_ascii=True, indent=2))
        if read("기존 토큰을 암호화 저장·조회 검증할까요? Proxmox 토큰·권한은 변경하지 않습니다. [yes/아니오]: ").strip() != "yes":
            return {"ok": True, "data": row}
        row = step("import-env", plan_digest=row["plan_digest"])
    elif row["phase"] in {"prepared", "authenticated", "mfa_required", "planned"}:
        row = authenticate()
        row = step("plan")
        output(json.dumps(row["plan"], ensure_ascii=True, indent=2))
        if not row["plan"]["can_confirm"]:
            return {"ok": False, "data": row, "message": "필요 권한을 확인한 뒤 다시 진행하세요.", "exit_code": 4}
        if read("표시한 token·role·ACL을 Proxmox에 생성할까요? [yes/아니오]: ").strip() != "yes":
            return {"ok": True, "data": row, "message": "계획을 보존했습니다. 아직 token을 생성하지 않았습니다."}
        row = step("confirm", plan_digest=row["plan_digest"])
    else:
        return {"ok": False, "data": row, "message": "발급 결과를 확인하거나 token을 정리해야 합니다. --resume으로 재개한 뒤 observe 또는 revoke를 선택하세요.", "exit_code": 5}
    if read("검증한 연결로 전환할까요? 전환 후 서버 재시작이 필요합니다. [yes/아니오]: ").strip() == "yes":
        row = step("activate")
    return {"ok": True, "data": row}
