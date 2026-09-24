"""Shared interactive registration for CLI and the minimal menu TUI."""
import json
from pathlib import Path
import time
import uuid

from .errors import ClientError


def wizard(app, *, read, password, output, attempt_id=None, include_compute=False, include_create=False, include_disk=False, include_network=False, include_clone=False, include_delete=False, include_console=False, include_template=False, include_image_build=False, include_image_cleanup=False, include_backup=False, include_restore=False, include_migrate=False, include_host_storage=False, include_host_network=False):
    if attempt_id:
        row = app.proxmox_setup("status", attempt_id=attempt_id)["data"]
    else:
        output("기존 연결의 권한을 갱신하려면 같은 대상에 새 토큰을 등록·검증한 뒤 전환하세요. 이전 토큰은 자동 폐기하지 않으며 전환 후 모든 서버 프로세스 재시작이 필요합니다.")
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
        if include_compute and read("선택한 VM의 CPU·메모리 변경 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("compute")
        if include_disk and read("선택한 VM의 디스크 확장·storage 공간 할당 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("disk")
        if include_network and read("선택한 VM의 NIC bridge·VLAN 변경과 bridge 사용 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("network")
        if include_migrate and read("선택한 정지 VM의 shared NFS 노드 이동 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("migrate")
            output("조회 node를 최소 두 개 선택하세요. VM.Migrate/Config.Disk와 선택 bridge 사용 권한을 추가합니다. storage 할당·host 수정·자동 부팅 권한은 추가하지 않습니다.")
        creation_scope = {}
        if include_create and read("템플릿에서 새 VM을 생성하는 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("create")
            output("생성 대상 VMID에 할당·설정·전원·guest-agent 실행 권한이 포함됩니다. Gjallar는 cloud-init 상태 확인 명령만 실행하지만 PVE token 자체의 guest-agent 권한은 더 넓습니다.")
            try:
                creation_scope = {
                    "template_vmids": [int(value.strip()) for value in read("복제 원본 템플릿 ID (쉼표 구분): ").split(",") if value.strip()],
                    "create_vmids": [int(value.strip()) for value in read("생성할 VM ID (쉼표 구분, 기존 VM/원본과 분리): ").split(",") if value.strip()],
                }
            except ValueError:
                raise ClientError("INVALID_VMID", "VMID는 숫자로 입력하세요.", 2) from None
        if include_delete and read("선택한 VM의 전체 영구 삭제 권한(VM.Allocate, 선택 storage의 Datastore.Allocate 필요)도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("delete")
            output("VM ACL 제거 후 disk 부재를 확인하려면 storage Allocate가 필요합니다. PVE 토큰 자체는 선택 storage 설정·다른 내용 삭제 권한도 가지므로 범위를 검토하세요. Gjallar는 검토한 VM 삭제만 허용합니다.")
        if include_console and read("선택한 기존 VM의 화면·키보드·마우스 콘솔 권한(VM.Console)도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("console")
        if include_template and read("선택한 기존 VM의 템플릿 전환 권한(VM.Allocate·Config.Disk, storage 조회 필요)도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("template")
        clone_scope = {}
        if include_clone and read("선택한 일반 VM의 full clone 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("clone")
            output("원본·대상의 disk 조회에 Config.Disk가 필요합니다. PVE 토큰은 disk 변경도 가능하지만 Gjallar는 검토한 복제만 허용합니다.")
            try:
                clone_scope = {"clone_vmids": [int(value.strip()) for value in read("복제할 새 VM ID (쉼표 구분, 기존/생성/템플릿과 분리): ").split(",") if value.strip()]}
            except ValueError:
                raise ClientError("INVALID_VMID", "VMID는 숫자로 입력하세요.", 2) from None
        image_scope = {}
        if include_image_build and read("공식 이미지로 새 템플릿을 제작하는 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("image_build")
            output("선택 storage의 import 업로드·공간 할당과 새 VM 설정·템플릿 전환 권한을 포함합니다. 제작 중 VM은 부팅하지 않습니다.")
            try:
                image_scope = {"image_vmids": [int(value.strip()) for value in read("제작할 새 템플릿 ID (쉼표 구분, 다른 VM 범위와 분리): ").split(",") if value.strip()]}
            except ValueError:
                raise ClientError("INVALID_VMID", "VMID는 숫자로 입력하세요.", 2) from None
        cleanup_scope = {}
        if include_image_cleanup and read("완료된 이미지 제작 자원 정리 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("image_cleanup")
            output("기존 VMID 중 성공한 제작 소유 자원만 정리합니다. 선택 storage의 Datastore.Allocate는 PVE 토큰 자체로 storage 설정·다른 내용 삭제도 가능하므로 필요한 범위만 선택하세요.")
            cleanup_scope = {"image_cleanup_storages": [value.strip() for value in read("정리 권한을 부여할 storage ID (위 조회 storage의 부분집합, 쉼표 구분): ").split(",") if value.strip()]}
        backup_scope = {}
        if include_backup and read("선택한 VM의 백업 조회·생성 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("backup")
            output("원본 VM.Backup와 선택 backup storage의 AllocateSpace 권한을 사용합니다. Gjallar는 기존 백업 삭제·보존 정책 변경을 허용하지 않습니다.")
            backup_scope = {"backup_storages": [value.strip() for value in read("백업 storage ID (위 조회 storage의 부분집합, 쉼표 구분): ").split(",") if value.strip()]}
        restore_scope = {}
        if include_restore and read("별도 VMID로 백업 복원·격리 부팅 검사 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("restore")
            output("원본 백업 읽기·새 VM 할당/조회/전원/agent 조회·disk 확인·선택 storage 공간·bridge 사용 권한을 포함합니다. 자동 시작·NIC 연결·덮어쓰기는 허용하지 않습니다.")
            if not backup_scope:
                backup_scope = {"backup_storages": [value.strip() for value in read("읽을 백업 storage ID (조회 storage의 부분집합, 쉼표 구분): ").split(",") if value.strip()]}
            try:
                restore_scope["restore_vmids"] = [int(value.strip()) for value in read("복원할 새 VM ID (모든 기존/생성/제작 범위와 분리, 쉼표 구분): ").split(",") if value.strip()]
            except ValueError:
                raise ClientError("INVALID_VMID", "VMID는 숫자로 입력하세요.", 2) from None
            restore_scope["restore_storages"] = [value.strip() for value in read("복원 대상 NFS images storage ID (조회 storage의 부분집합, 쉼표 구분): ").split(",") if value.strip()]
        host_scope = {}
        if include_host_storage and read("directory storage 등록·수정 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("host_storage")
            output("PVE token은 /storage의 Datastore.Allocate로 클러스터 전체 storage 설정을 변경할 수 있습니다. Gjallar는 선택한 host storage ID와 허용된 directory 설정만 변경합니다.")
            host_scope = {"host_storages": [value.strip() for value in read("설정할 host storage ID (신규 ID 포함, 쉼표 구분): ").split(",") if value.strip()]}
        if include_host_network and read("VM용 bridge 설정·노드 전체 네트워크 반영 권한도 부여할까요? [yes/아니오]: ").strip() == "yes":
            features.append("host_network")
            output("PVE token은 선택 node의 Sys.Modify와 전체 local bridge 조회 권한이 필요합니다. Gjallar는 선택 bridge 설정만 변경하지만 실제 반영은 노드 전체 네트워크에 영향을 줍니다.")
            host_scope["host_bridges"] = [value.strip() for value in read("설정할 host bridge (신규 vmbrN 포함, 쉼표 구분): ").split(",") if value.strip()]
        row = app.proxmox_setup("prepare", body={"idempotency_key": str(uuid.uuid4()), "intent": {
            "endpoint": endpoint, "owner": owner, "ca_pem": ca_pem,
            "scope": {"nodes": nodes, "vmids": vmids, "storages": storages, "bridges": bridges, **creation_scope, **clone_scope, **image_scope, **cleanup_scope, **backup_scope, **restore_scope, **host_scope},
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


def simple_wizard(app, *, read, password, output, attempt_id=None):
    """Connect a whole cluster with one credential and one durable token."""
    if attempt_id:
        row = app.proxmox_setup('status', attempt_id=attempt_id)['data']
        if row.get('access_mode') != 'cluster':
            return wizard(app, read=read, password=password, output=output, attempt_id=attempt_id)
    else:
        endpoint = read('Proxmox 주소 (IP 또는 HTTPS 주소): ').strip()
        if '://' not in endpoint:
            endpoint = 'https://' + endpoint
        owner = read('Proxmox 계정 [root]: ').strip() or 'root'
        if '@' not in owner:
            owner += '@pam'
        trust = app.proxmox_setup('trust', body={'endpoint': endpoint})['data']
        output('서버 인증서 SHA256: ' + trust['certificate_sha256'])
        if read('이 Proxmox 인증서를 신뢰하고 저장할까요? [yes/아니오]: ').strip() != 'yes':
            return {'ok': True, 'message': '연결을 취소했습니다.'}
        row = app.proxmox_setup('prepare', body={'idempotency_key': str(uuid.uuid4()), 'intent': {
            'endpoint': trust['endpoint'], 'owner': owner, 'certificate_sha256': trust['certificate_sha256'],
            'scope': {}, 'access_mode': 'cluster', 'mode': 'issue',
            'expires_at': int(time.time()) + 30 * 86400,
        }})['data']
    output('등록 ID: ' + row['attempt_id'] + ' · 중단 시 proxmox-setup --resume ' + row['attempt_id'])

    def step(action, **fields):
        return app.proxmox_setup(action, attempt_id=row['attempt_id'],
                                 body={'expected_version': row['version'], **fields})['data']

    if row['phase'] == 'active':
        return {'ok': True, 'data': row, 'message': '연결이 저장됐습니다. 모든 Gjallar 서버 프로세스를 재시작한 뒤 자원을 조회하세요.'}
    if row['phase'] in {'cancelled', 'revoked'}:
        return {'ok': True, 'data': row, 'message': '종료된 등록입니다. --resume 없이 새 연결을 시작하세요.'}
    if row['phase'] in {'prepared', 'authenticated', 'mfa_required', 'planned'}:
        row = step('login', password=password('Proxmox 비밀번호: '))
        if row.get('mfa_required'):
            row = step('mfa', otp=password('TOTP: '))
        row = step('plan')
        if not row['plan']['can_confirm']:
            return {'ok': False, 'data': row, 'message': '토큰 발급에 필요한 Proxmox 계정 권한이 부족합니다.', 'exit_code': 4}
        output('현재와 이후 추가되는 전체 노드·VM·스토리지에 Gjallar의 관리 권한을 부여합니다. 토큰 유효기간은 30일이며 비밀번호는 저장하지 않습니다.')
        if read('전용 토큰을 발급·저장하고 이 연결을 사용할까요? [yes/아니오]: ').strip() != 'yes':
            return {'ok': True, 'data': row, 'message': '계획을 보존했습니다. 아직 토큰을 발급하지 않았습니다.'}
        row = step('confirm', plan_digest=row['plan_digest'])
    elif row['phase'] in {'secret_staged', 'verifying', 'acl_applying', 'acl_unknown', 'verified'}:
        # Observation only: never replay token creation or ACL mutations after interruption.
        row = step('verify')
        if read('검증한 전체 연결을 사용할까요? [yes/아니오]: ').strip() != 'yes':
            return {'ok': True, 'data': row}
    else:
        return {'ok': False, 'data': row, 'exit_code': 5,
                'message': '발급 결과 확인이 필요합니다. proxmox-setup --advanced --resume ' + row['attempt_id'] + '에서 observe로 확인하세요.'}
    row = step('activate')
    return {'ok': True, 'data': row,
            'message': '전용 토큰을 암호화 저장했습니다. 모든 Gjallar 서버 프로세스를 재시작하면 Gjallar 로그인으로 전체 자원을 관리할 수 있습니다. 이전 토큰은 자동 폐기하지 않습니다.'}
