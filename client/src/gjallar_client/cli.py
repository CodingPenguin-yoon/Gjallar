"""CLI entry point; secrets are prompted, never accepted as arguments."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import warnings

from .application import Application
from .connections import Connections
from .errors import ClientError
from .sessions import KeyringStore, MemoryStore
from . import tui


def prompt(message):
    print(message, end="", file=sys.stderr, flush=True)
    return input()


def secure_password(message):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(message)
        except getpass.GetPassWarning:
            raise ClientError("SECURE_INPUT_REQUIRED", "비표시 비밀번호 입력이 가능한 터미널에서 실행하세요.", 2) from None


def administrator(read=prompt, password=secure_password):
    username = read("최초 Gjallar 관리자 계정: ")
    first = password("새 비밀번호: ")
    if not first or first != password("비밀번호 확인: "):
        raise ClientError("PASSWORD_MISMATCH", "비밀번호가 비었거나 확인 값이 다릅니다. 같은 설치 경로로 다시 실행하세요.", 2)
    return {"username": username, "password": first}


def login_local(app, result, read=prompt, password=secure_password):
    origin = result["url"]
    name = "local-" + origin.rsplit(":", 1)[-1]
    profiles = app.connections.read()["connections"]
    if name not in profiles:
        app.connections.add(name, origin)
    elif profiles[name]["origin"] != origin:
        raise ClientError("CONNECTION_CONFLICT", "로컬 연결 별칭이 다른 서버에 사용 중입니다. 새 별칭으로 직접 연결하세요.")
    return app.login(read("Gjallar 로그인 계정 (설치 시 만든 계정, 예: admin): "), password("Gjallar 비밀번호: "), name)


def local_start(app, read, password, output):
    from .bootstrap import Bootstrap
    path = read("설치 경로 (Enter: ~/.local/share/gjallar): ") or str(Path.home() / ".local/share/gjallar")
    port = read("loopback port (Enter: 8000): ") or "8000"
    if not port.isdigit():
        raise ClientError("INVALID_PORT", "숫자 port를 입력하세요.", 2)
    image = read("Gjallar 이미지 (Enter: 기존 이미지 유지 / 신규 gjallar:local): ") or None
    result = Bootstrap(Path(path)).install(image=image, port=int(port), administrator=lambda: administrator(read, password))
    tui.show(result, output)
    tui.show(login_local(app, result, read, password), output)
    tui.show(app.read("connection"), output)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ClientError("INVALID_ARGUMENT", "명령 또는 인자가 올바르지 않습니다. 해당 명령의 --help를 확인하세요.", 2)


def positive_id(value):
    try:
        number = int(value)
        if number < 100 or number > 999999999:
            raise ValueError
        return number
    except ValueError:
        raise argparse.ArgumentTypeError("VMID는 100~999999999 정수입니다.") from None


def parser():
    common = Parser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument("--config-dir", type=Path, help="클라이언트 연결 설정 디렉터리")
    common.add_argument("--session-mode", choices=["keyring", "memory"], help="기본 keyring; memory는 shell에서 연속 사용")
    common.add_argument("--connection", help="이번 명령에 사용할 저장된 서버 별칭")
    output = common.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="자동화용 JSON 한 개 출력")
    output.add_argument("--human", action="store_true", help="파이프에서도 사람이 읽는 출력")
    result = Parser(description="Gjallar · 설치, 연결, VM 운영", parents=[common],
                    epilog="시작: connect → login → connection status → vms. 전체 화면은 tui, 비저장 연속 사용은 shell.")
    commands = result.add_subparsers(dest="command")
    def add(group, name, **kwargs):
        return group.add_parser(name, parents=[common], **kwargs)
    connect = add(commands, "connect", help="Gjallar 서버 주소를 별칭으로 저장")
    connect.add_argument("name")
    connect.add_argument("origin")
    connect.add_argument("--ca-file")
    connect.add_argument("--cookie-name", default="gjallar_session")
    connection = add(commands, "connection", help="저장된 서버 목록·선택·Proxmox 관찰 상태")
    connection.add_argument("action", choices=["list", "use", "status"])
    connection.add_argument("name", nargs="?")
    login = add(commands, "login", help="설치 시 만든 Gjallar 계정으로 로그인")
    login.add_argument("--username", help="계정명 (비밀번호는 비표시 입력)")
    for name, help_text in [("logout", "Gjallar session 폐기"), ("status", "현재 서버·계정 확인"),
                            ("nodes", "노드 목록"), ("vms", "VM 목록"), ("templates", "템플릿 목록"),
                            ("tui", "전체 화면 TUI"), ("shell", "같은 session으로 CLI 명령 연속 실행")]:
        add(commands, name, help=help_text)
    vm = add(commands, "vm", help="VM 조회·시작·정상 종료·생성·CPU/메모리 변경")
    host = add(commands, 'host', help='관리자 호스트 설정')
    host_kinds = host.add_subparsers(dest='kind', required=True)
    host_storage = add(host_kinds, 'storage', help='directory storage 등록·수정')
    storage_stages = host_storage.add_subparsers(dest='stage', required=True)
    storage_plan = add(storage_stages, 'plan', help='설정 변경 검토 파일 저장 (아직 실행하지 않음)')
    storage_plan.add_argument('storage')
    storage_plan.add_argument('--node',required=True)
    storage_plan.add_argument('--mode',choices=['create','update'],required=True)
    storage_plan.add_argument('--directory')
    storage_plan.add_argument('--content',nargs='+',required=True,choices=['images','iso','backup','import','snippets','vztmpl','rootdir'])
    storage_plan.add_argument('--disable',action='store_true')
    storage_plan.add_argument('--request-id',required=True)
    storage_plan.add_argument('--confirmation',required=True)
    storage_plan.add_argument('--ack-cluster-impact',action='store_true')
    storage_plan.add_argument('--review-file',type=Path,required=True)
    storage_execute = add(storage_stages, 'execute', help='검토한 설정 한 번 실행·결과 확인')
    storage_execute.add_argument('--review-file',type=Path,required=True)
    storage_execute.add_argument('--yes',action='store_true')
    host_network = add(host_kinds, 'network', help='VM용 Linux bridge 설정·노드 전체 반영')
    network_stages = host_network.add_subparsers(dest='stage', required=True)
    bridge_plan = add(network_stages, 'plan', help='bridge 변경 검토 저장 (실행 없음)')
    bridge_plan.add_argument('bridge')
    bridge_plan.add_argument('--node', required=True)
    bridge_plan.add_argument('--mode', choices=['create', 'update'], required=True)
    bridge_plan.add_argument('--no-autostart', action='store_true')
    bridge_plan.add_argument('--vlan-aware', action='store_true')
    bridge_plan.add_argument('--vlan-ids')
    bridge_plan.add_argument('--request-id', required=True)
    bridge_plan.add_argument('--confirmation', required=True)
    bridge_plan.add_argument('--ack-node-reload', action='store_true')
    bridge_plan.add_argument('--review-file', type=Path, required=True)
    bridge_execute = add(network_stages, 'execute', help='검토한 bridge 저장·노드 전체 반영·결과 확인')
    bridge_execute.add_argument('--review-file', type=Path, required=True)
    bridge_execute.add_argument('--yes', action='store_true')
    maintenance = add(commands, 'maintenance', help='노드 영향·VM별 유지보수 준비 조회 (실행 없음)')
    maintenance_kinds = maintenance.add_subparsers(dest='kind', required=True)
    maintenance_node = add(maintenance_kinds, 'node', help='현재 연결의 QEMU 영향·백업·이동 준비 보고서')
    maintenance_node.add_argument('node')
    maintenance_node.add_argument('--destination')
    maintenance_node.add_argument('--backup-storage')
    maintenance_node.add_argument('--backup-max-age-hours', type=int, default=24, choices=range(1,721), metavar='1~720')
    maintenance_node.add_argument('--check-limit', type=int, default=10, choices=range(1,21), metavar='1~20')
    metrics = add(commands, 'metrics', help='현재 사용량·PVE 평균 이력 조회')
    alerts = add(commands, 'alerts', help='최신 작업의 실패·복구 이력 (자원 임계 이력은 metrics)')
    alerts.add_argument('--limit', type=int, default=20, choices=range(1, 51), metavar='1~50')
    metric_targets = metrics.add_subparsers(dest='kind', required=True)
    for kind in ('node', 'vm', 'storage'):
        command = add(metric_targets, kind, help='선택 자원의 현재 값·추이·누락·해상도 조회')
        command.add_argument('resource', type=positive_id if kind == 'vm' else str)
        if kind != 'node': command.add_argument('--node', required=True)
        command.add_argument('--timeframe', choices=['hour', 'day', 'week', 'month', 'year'], default='hour')
    actions = vm.add_subparsers(dest="action", required=True)
    add(actions, "list", help="VM 목록")
    show = add(actions, "show", help="VM 상세")
    show.add_argument("vmid", type=positive_id)
    for action, label in [("start", "VM 시작"), ("shutdown", "VM 정상 종료 (강제 종료 없음)")]:
        command = add(actions, action, help=label)
        command.add_argument("vmid", type=positive_id)
        command.add_argument("--node", required=True)
        command.add_argument("--request-id", required=True, help="한 실행 의도의 고유 ID; 응답 유실 시 보존")
        command.add_argument("--yes", action="store_true", help="표시된 대상 변경에 명시적으로 동의")
    create = add(actions, "create", help="서버 생성 계획을 검토한 뒤 별도 실행")
    template_test = add(actions, 'template-test', help='생성 Operation의 배포 검사·운영자 접속 결과')
    test_stages = template_test.add_subparsers(dest='stage', required=True)
    test_show = add(test_stages, 'show', help='생성 당시 검사와 접속 증거 조회 (현재 상태 아님)')
    test_show.add_argument('operation_id')
    test_access = add(test_stages, 'record-access', help='직접 확인한 접속 결과 기록 (SSH 실행 없음)')
    test_access.add_argument('operation_id')
    test_access.add_argument('--status', choices=['passed', 'failed', 'not_run', 'unavailable'], required=True)
    test_access.add_argument('--request-id', required=True)
    test_access.add_argument('--ack-evidence', action='store_true')
    backup = add(actions, 'backup', help='NFS 백업 목록·검토·명시적 생성')
    backup_stages = backup.add_subparsers(dest='stage', required=True)
    for stage in ('list', 'plan'):
        command = add(backup_stages, stage, help='백업 목록 조회' if stage == 'list' else '백업 검토 파일 저장')
        command.add_argument('vmid', type=positive_id)
        command.add_argument('--node', required=True)
        command.add_argument('--storage', required=True)
        if stage == 'plan':
            command.add_argument('--confirmation', required=True)
            command.add_argument('--ack-backup', action='store_true')
            command.add_argument('--request-id', required=True)
            command.add_argument('--review-file', type=Path, required=True)
    backup_execute = add(backup_stages, 'execute', help='검토한 백업 한 번 실행·실제 결과 확인')
    backup_execute.add_argument('--review-file', type=Path, required=True)
    backup_execute.add_argument('--yes', action='store_true')
    restore = add(actions, 'restore', help='별도 VMID 격리 복원·검사 보고서')
    restore_stages = restore.add_subparsers(dest='stage', required=True)
    restore_plan = add(restore_stages, 'plan', help='격리 복원 검토 파일 저장')
    restore_plan.add_argument('vmid', type=positive_id)
    for flag in ('node','archive','name','storage','bridge','confirmation','request-id'):
        restore_plan.add_argument('--'+flag, required=True)
    restore_plan.add_argument('--new-vmid', type=positive_id, required=True)
    restore_plan.add_argument('--ack-isolation', action='store_true')
    restore_plan.add_argument('--review-file', type=Path, required=True)
    restore_execute = add(restore_stages, 'execute', help='검토한 복원 한 번 실행·실제 결과 확인')
    restore_execute.add_argument('--review-file', type=Path, required=True)
    restore_execute.add_argument('--yes', action='store_true')
    restore_report = add(restore_stages, 'report', help='현재 복원 VM·원본·백업·전원·agent 조회')
    restore_report.add_argument('operation_id')
    migrate = add(actions, 'migrate', help='정지 VM shared NFS 노드 이동')
    migrate_stages = migrate.add_subparsers(dest='stage', required=True)
    for stage in ('show','plan'):
        command = add(migrate_stages,stage,help='이동 조건 조회' if stage=='show' else '이동 검토 파일 저장')
        command.add_argument('vmid',type=positive_id)
        command.add_argument('--node',required=True)
        command.add_argument('--destination',required=True)
        if stage=='plan':
            command.add_argument('--confirmation',required=True)
            command.add_argument('--ack-migration',action='store_true')
            command.add_argument('--request-id',required=True)
            command.add_argument('--review-file',type=Path,required=True)
    migrate_execute = add(migrate_stages,'execute',help='검토한 정지 VM 이동 한 번 실행')
    migrate_execute.add_argument('--review-file',type=Path,required=True)
    migrate_execute.add_argument('--yes',action='store_true')
    compute = add(actions, "compute", help="정지 VM CPU·메모리 조회·검토·변경")
    compute_stages = compute.add_subparsers(dest="stage", required=True)
    for stage in ('show', 'plan'):
        command = add(compute_stages, stage, help='현재 설정 조회' if stage == 'show' else '변경 전후 검토 파일 저장 (VM 변경 없음)')
        command.add_argument('vmid', type=positive_id)
        command.add_argument('--node', required=True)
        if stage == 'plan':
            command.add_argument('--cores', type=int, required=True)
            command.add_argument('--memory-mib', type=int, required=True)
            command.add_argument('--request-id', required=True)
            command.add_argument('--review-file', type=Path, required=True)
    compute_execute = add(compute_stages, 'execute', help='같은 검토 파일의 변경 실행·실제 결과 확인')
    compute_execute.add_argument('--review-file', type=Path, required=True)
    compute_execute.add_argument('--yes', action='store_true')
    disk = add(actions, 'disk', help='정지 VM의 NFS scsi0 디스크 조회·확장')
    disk_stages = disk.add_subparsers(dest='stage', required=True)
    for stage in ('show', 'plan'):
        command = add(disk_stages, stage, help='현재 실제 용량 조회' if stage == 'show' else '확장 검토 파일 저장')
        command.add_argument('vmid', type=positive_id)
        command.add_argument('--node', required=True)
        if stage == 'plan':
            command.add_argument('--size-gib', type=int, required=True, help='추가분이 아닌 확장 후 전체 GiB')
            command.add_argument('--request-id', required=True)
            command.add_argument('--review-file', type=Path, required=True)
    disk_execute = add(disk_stages, 'execute', help='검토한 디스크 확장 실행·실제 용량 확인')
    disk_execute.add_argument('--review-file', type=Path, required=True)
    disk_execute.add_argument('--yes', action='store_true')
    network = add(actions, 'network', help='정지 VM의 기존 net0 bridge·VLAN 변경')
    network_stages = network.add_subparsers(dest='stage', required=True)
    for stage in ('show', 'plan'):
        command = add(network_stages, stage, help='현재 NIC·bridge 조회' if stage == 'show' else 'NIC 변경 검토 파일 저장')
        command.add_argument('vmid', type=positive_id)
        command.add_argument('--node', required=True)
        if stage == 'plan':
            command.add_argument('--bridge', required=True)
            vlan = command.add_mutually_exclusive_group(required=True)
            vlan.add_argument('--vlan-tag', type=int)
            vlan.add_argument('--untagged', action='store_true')
            command.add_argument('--request-id', required=True)
            command.add_argument('--review-file', type=Path, required=True)
    network_execute = add(network_stages, 'execute', help='검토한 NIC 변경 실행·실제 설정 확인')
    network_execute.add_argument('--review-file', type=Path, required=True)
    network_execute.add_argument('--yes', action='store_true')
    clone = add(actions, 'clone', help='정지 VM의 같은 노드 NFS full clone')
    clone_stages = clone.add_subparsers(dest='stage', required=True)
    for stage in ('show', 'plan'):
        command = add(clone_stages, stage, help='원본·새 VMID·storage 조회' if stage == 'show' else '복제 검토 파일 저장')
        command.add_argument('vmid', type=positive_id)
        command.add_argument('--node', required=True)
        command.add_argument('--new-vmid', type=positive_id, required=True)
        command.add_argument('--storage', required=True)
        if stage == 'plan':
            command.add_argument('--name', required=True)
            command.add_argument('--ack-guest-identity', action='store_true', help='복제되는 guest IP·hostname·SSH host key 위험 확인')
            command.add_argument('--request-id', required=True)
            command.add_argument('--review-file', type=Path, required=True)
    clone_execute = add(clone_stages, 'execute', help='검토한 full clone 실행·새 VM 확인')
    clone_execute.add_argument('--review-file', type=Path, required=True)
    clone_execute.add_argument('--yes', action='store_true')
    console = add(actions, 'console', help='선택 VM의 웹 콘솔 접속 안내 (브라우저 로그인 필요)')
    console.add_argument('vmid', type=positive_id)
    console.add_argument('--node', required=True)
    deletion = add(actions, 'delete', help='정지 VM과 연결 소유 disk의 영구 삭제')
    deletion_stages = deletion.add_subparsers(dest='stage', required=True)
    for stage in ('show', 'plan'):
        command = add(deletion_stages, stage, help='삭제·보존 자원 조회' if stage == 'show' else '명시적 삭제 검토 파일 저장')
        command.add_argument('vmid', type=positive_id)
        command.add_argument('--node', required=True)
        if stage == 'plan':
            command.add_argument('--confirmation', required=True, help='조회한 VMID/이름 그대로 입력')
            command.add_argument('--ack-delete', action='store_true', help='VM·disk 영구 삭제와 자동 복구 불가 확인')
            command.add_argument('--request-id', required=True)
            command.add_argument('--review-file', type=Path, required=True)
    deletion_execute = add(deletion_stages, 'execute', help='검토한 삭제 실행·VMID와 volume 부재 확인')
    deletion_execute.add_argument('--review-file', type=Path, required=True)
    deletion_execute.add_argument('--yes', action='store_true')
    conversion = add(actions, 'template', help='준비된 정지 VM의 템플릿 전환')
    conversion_stages = conversion.add_subparsers(dest='stage', required=True)
    for stage in ('show', 'plan'):
        command = add(conversion_stages, stage, help='전환·보존 자원 조회' if stage == 'show' else '명시적 전환 검토 파일 저장')
        command.add_argument('vmid', type=positive_id)
        command.add_argument('--node', required=True)
        if stage == 'plan':
            command.add_argument('--confirmation', required=True, help='조회한 VMID/이름 그대로 입력')
            command.add_argument('--guest-prepared', action='store_true', help='계정/키·machine-id·cloud-init·네트워크 배포 준비 확인')
            command.add_argument('--ack-conversion', action='store_true', help='VM·disk 영구 전환와 자동 복구 불가 확인')
            command.add_argument('--request-id', required=True)
            command.add_argument('--review-file', type=Path, required=True)
    conversion_execute = add(conversion_stages, 'execute', help='검토한 전환 실행·template과 base volume 확인')
    conversion_execute.add_argument('--review-file', type=Path, required=True)
    conversion_execute.add_argument('--yes', action='store_true')
    image_cleanup = add(actions, 'image-cleanup', help='완료된 제작 소유 template 또는 업로드 원본 정리')
    cleanup_stages = image_cleanup.add_subparsers(dest='stage', required=True)
    for stage in ('show', 'plan'):
        command = add(cleanup_stages, stage, help='소유 삭제·보존 자원 조회' if stage == 'show' else '영구 삭제 검토 파일 저장')
        command.add_argument('vmid', type=positive_id)
        command.add_argument('--node', required=True)
        command.add_argument('--build-operation', required=True)
        command.add_argument('--resource', choices=['template', 'source'], required=True)
        if stage == 'plan':
            command.add_argument('--confirmation', required=True, help='VMID/이름/template 또는 VMID/이름/source')
            command.add_argument('--ack-cleanup', action='store_true', help='선택 소유 자원 영구 삭제 확인')
            command.add_argument('--request-id', required=True)
            command.add_argument('--review-file', type=Path, required=True)
    cleanup_execute = add(cleanup_stages, 'execute', help='검토한 자원 삭제·부재 확인')
    cleanup_execute.add_argument('--review-file', type=Path, required=True)
    cleanup_execute.add_argument('--yes', action='store_true')
    image_build = add(actions, 'image-build', help='고정 공식 cloud image로 새 템플릿 제작')
    image_stages = image_build.add_subparsers(dest='stage', required=True)
    add(image_stages, 'catalog', help='지원 공식 이미지·출처·체크섬 조회')
    for stage in ('show', 'plan'):
        command = add(image_stages, stage, help='제작 대상 검토' if stage == 'show' else '제작 검토 파일 저장')
        command.add_argument('vmid', type=positive_id)
        command.add_argument('--node', required=True)
        command.add_argument('--image-id', required=True)
        command.add_argument('--name', required=True)
        command.add_argument('--storage', required=True)
        command.add_argument('--staging-storage', required=True)
        command.add_argument('--bridge', required=True)
        if stage == 'plan':
            command.add_argument('--confirmation', required=True, help='새 VMID/이름 그대로 입력')
            command.add_argument('--ack-image-build', action='store_true', help='이미지 업로드·공간 소모·VM 생성·전환 영향 확인')
            command.add_argument('--request-id', required=True)
            command.add_argument('--review-file', type=Path, required=True)
    image_execute = add(image_stages, 'execute', help='검토한 제작 실행·실제 템플릿 확인')
    image_execute.add_argument('--review-file', type=Path, required=True)
    image_execute.add_argument('--yes', action='store_true')
    stages = create.add_subparsers(dest="stage", required=True)
    add(stages, "example", help="편집할 생성 입력 JSON 예제 출력")
    plan = add(stages, "plan", help="서버에 계획 기록 (VM 변경 없음)")
    plan.add_argument("--file", type=Path, required=True, help="생성 입력 JSON")
    plan.add_argument("--request-id", required=True)
    plan.add_argument("--review-file", type=Path, required=True, help="새 검토 파일 경로 (0600, 덮어쓰기 금지)")
    execute = add(stages, "execute", help="검토 파일과 서버 승인을 검증하고 VM 생성")
    execute.add_argument("--review-file", type=Path, required=True)
    execute.add_argument("--ack-yellow", action="store_true", help="검토한 yellow 위험·IP 확인에 동의")
    execute.add_argument("--yes", action="store_true")
    operations = add(commands, "operations", help="웹과 같은 작업의 상태·결과 조회")
    queries = operations.add_subparsers(dest="action", required=True)
    listing = add(queries, "list", help="최근 작업; VM/상태로 필터")
    listing.add_argument("--vmid", type=positive_id)
    listing.add_argument("--status")
    listing.add_argument("--limit", type=int, default=50, choices=range(1,201), metavar="1..200")
    show = add(queries, "show", help="작업 결과·이벤트·복구 상태")
    show.add_argument("operation_id")
    setup = add(commands, "proxmox-setup", help="관리자용 Proxmox 연결 등록")
    setup.add_argument("--advanced", action="store_true", help="대상·기능별 제한 또는 기존 토큰 가져오기")
    setup.add_argument("--resume")
    setup.add_argument("--list", action="store_true")
    install = add(commands, "bootstrap", help="로컬 설치·시작 (로그인은 별도 login)")
    install.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    install.add_argument("--image")
    install.add_argument("--port", type=int, default=8000)
    install.add_argument("--bind-address", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1", help="웹 공개 주소 (기본 loopback)")
    service = add(commands, "service", help="로컬 서비스 상태·시작·종료")
    service.add_argument("action", choices=["start", "status", "stop"])
    service.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    upgrade = add(commands, "upgrade", help="같은 DB schema의 이미지로 업그레이드")
    upgrade.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    upgrade.add_argument("--image", required=True)
    return result


def login_name(connections, requested):
    data = connections.read()
    if requested or data['selected']:
        return connections.get(requested)[0]
    names = list(data['connections'])
    if len(names) == 1:
        return names[0]
    raise ClientError('NO_CONNECTION', '로그인할 서버를 --connection으로 지정하세요. connection list에서 별칭을 확인할 수 있습니다.', 2)


def confirm_change(summary, yes):
    from .output import human
    print(human({'data': summary}), file=sys.stderr)
    if yes:
        return
    if not sys.stdin.isatty():
        raise ClientError('CONFIRMATION_REQUIRED', '대상·영향을 검토한 뒤 --yes로 실행에 동의하세요.', 2)
    if prompt('이 변경을 실행할까요? [yes/취소]: ').strip() != 'yes':
        raise ClientError('CANCELLED', '실행을 취소했습니다. 변경 요청을 보내지 않았습니다.', 2)


def shell(args, connections, sessions):
    import shlex
    if not sys.stdin.isatty():
        raise ClientError('TERMINAL_REQUIRED', 'shell은 대화형 터미널에서 실행하세요.', 2)
    print('Gjallar CLI · help 도움말 · exit 종료. 비밀번호는 로그인에서만 입력하세요.', file=sys.stderr)
    prefix = ['--config-dir', str(connections.directory), '--session-mode', args.session_mode]
    if args.connection:
        prefix += ['--connection', args.connection]
    while True:
        try:
            command = prompt('gjallar> ').strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if command in {'exit', 'quit'}:
            return 0
        if not command:
            continue
        if command == 'help':
            parser().print_help()
            continue
        try:
            argv = shlex.split(command)
        except ValueError:
            print('따옴표가 닫혔는지 확인하세요.', file=sys.stderr)
            continue
        try:
            main(prefix + argv, session_store=sessions, in_shell=True)
        except SystemExit as exc:
            if exc.code:
                print('명령 도움말을 확인하세요.', file=sys.stderr)


def execute(args, app):
    from . import workflows
    if args.command == 'login':
        name = login_name(app.connections, args.connection)
        app.connections.get(name)  # Validate before requesting credentials.
        return app.login(args.username or prompt(f'Gjallar 계정 ({name}, 예: admin): '), secure_password('비밀번호: '), name)
    if args.command == 'logout':
        return app.logout(args.connection)
    if args.command == 'status':
        return app.status(args.connection)
    if args.command == 'connection':
        if args.action == 'use':
            if not args.name:
                raise ClientError('MISSING_NAME', '선택할 연결 별칭이 필요합니다.', 2)
            return app.use(args.name)
        return app.read('connection')
    if args.command in {'nodes', 'vms', 'templates'}:
        return app.read(args.command)
    if args.command == 'host' and args.kind == 'network':
        from . import host_network_workflow
        if args.stage == 'execute':
            return host_network_workflow.execute(app, args.review_file, lambda value: confirm_change(value, args.yes))
        return host_network_workflow.plan(app, node=args.node, bridge=args.bridge, mode=args.mode,
            autostart=not args.no_autostart, vlan_aware=args.vlan_aware, vlan_ids=args.vlan_ids,
            request_id=args.request_id, confirmation=args.confirmation, acknowledge=args.ack_node_reload, review_file=args.review_file)
    if args.command == 'host':
        from . import host_storage_workflow
        if args.stage == 'execute':
            return host_storage_workflow.execute(app,args.review_file,lambda value:confirm_change(value,args.yes))
        return host_storage_workflow.plan(app,node=args.node,storage=args.storage,mode=args.mode,directory=args.directory,
            content=args.content,enabled=not args.disable,request_id=args.request_id,confirmation=args.confirmation,
            acknowledge=args.ack_cluster_impact,review_file=args.review_file)
    if args.command == 'maintenance':
        from .maintenance_workflow import show
        return show(app, node=args.node, destination=args.destination, backup_storage=args.backup_storage,
                    backup_max_age_hours=args.backup_max_age_hours, check_limit=args.check_limit)
    if args.command == 'metrics':
        from .metrics_workflow import show
        return show(app, kind=args.kind, node=args.resource if args.kind == 'node' else args.node,
                    resource=None if args.kind == 'node' else args.resource, timeframe=args.timeframe)
    if args.command == 'alerts':
        return app.request(f'monitoring/operation-alerts?limit={args.limit}')
    if args.command == 'operations':
        if args.action == 'show':
            return workflows.operations(app, operation_id=args.operation_id)
        return workflows.operations(app, vmid=args.vmid, status=args.status, limit=args.limit)
    if args.command == 'vm':
        if args.action == 'migrate':
            from . import migrate_workflow
            if args.stage=='execute':
                return migrate_workflow.execute(app,args.review_file,lambda value:confirm_change(value,args.yes))
            if args.stage=='show':
                return migrate_workflow.show(app,vmid=args.vmid,node=args.node,destination=args.destination)
            return migrate_workflow.plan(app,vmid=args.vmid,node=args.node,destination=args.destination,
                confirmation=args.confirmation,ack_migration=args.ack_migration,request_id=args.request_id,review_file=args.review_file)
        if args.action == 'restore':
            from . import restore_workflow
            if args.stage == 'execute':
                return restore_workflow.execute(app,args.review_file,lambda value:confirm_change(value,args.yes))
            if args.stage == 'report':
                return restore_workflow.report(app,args.operation_id)
            return restore_workflow.plan(app,vmid=args.vmid,node=args.node,archive=args.archive,new_vmid=args.new_vmid,
                name=args.name,storage=args.storage,bridge=args.bridge,confirmation=args.confirmation,
                ack_isolation=args.ack_isolation,request_id=args.request_id,review_file=args.review_file)
        if args.action == 'backup':
            from . import backup_workflow
            if args.stage == 'execute':
                return backup_workflow.execute(app, args.review_file, lambda value: confirm_change(value, args.yes))
            if args.stage == 'list':
                return backup_workflow.show(app, vmid=args.vmid, node=args.node, storage=args.storage)
            return backup_workflow.plan(app, vmid=args.vmid, node=args.node, storage=args.storage,
                confirmation=args.confirmation, backup_acknowledged=args.ack_backup, request_id=args.request_id, review_file=args.review_file)
        if args.action == 'list':
            return app.read('vms')
        if args.action == 'show':
            return app.request(f'vms/{args.vmid}')
        if args.action in {'start', 'shutdown'}:
            return workflows.power(app, args.action, args.vmid, args.node, args.request_id,
                                   lambda value: confirm_change(value, args.yes))
        if args.action == 'compute':
            from . import compute_workflow
            if args.stage == 'show':
                return compute_workflow.show(app, args.vmid, args.node)
            if args.stage == 'plan':
                return compute_workflow.plan(app, vmid=args.vmid, node=args.node, cores=args.cores,
                    memory_mib=args.memory_mib, request_id=args.request_id, review_file=args.review_file)
            return compute_workflow.execute(app, args.review_file, lambda value: confirm_change(value, args.yes))
        if args.action == 'template-test':
            from . import template_test_workflow
            if args.stage == 'show':
                return template_test_workflow.show(app, args.operation_id)
            return template_test_workflow.record_access(app, args.operation_id, status=args.status,
                request_id=args.request_id, acknowledged=args.ack_evidence)
        if args.action == 'console':
            from .console_workflow import guide
            return guide(app, vmid=args.vmid, node=args.node)
        if args.action == 'delete':
            from . import delete_workflow
            if args.stage == 'show':
                return delete_workflow.show(app, args.vmid, args.node)
            if args.stage == 'plan':
                return delete_workflow.plan(app, vmid=args.vmid, node=args.node, confirmation=args.confirmation,
                    delete_acknowledged=args.ack_delete, request_id=args.request_id, review_file=args.review_file)
            return delete_workflow.execute(app, args.review_file, lambda value: confirm_change(value, args.yes))
        if args.action == 'image-cleanup':
            from . import image_cleanup_workflow
            if args.stage == 'execute':
                return image_cleanup_workflow.execute(app, args.review_file, lambda value: confirm_change(value, args.yes))
            if args.stage == 'show':
                return image_cleanup_workflow.show(app, vmid=args.vmid, node=args.node,
                    parent_operation_id=args.build_operation, resource=args.resource)
            return image_cleanup_workflow.plan(app, vmid=args.vmid, node=args.node,
                parent_operation_id=args.build_operation, resource=args.resource, confirmation=args.confirmation,
                acknowledged=args.ack_cleanup, request_id=args.request_id, review_file=args.review_file)
        if args.action == 'image-build':
            from . import image_build_workflow
            if args.stage == 'catalog':
                return image_build_workflow.catalog(app)
            if args.stage == 'execute':
                return image_build_workflow.execute(app, args.review_file, lambda value: confirm_change(value, args.yes))
            configuration = {'image_id': args.image_id, 'name': args.name, 'storage_id': args.storage,
                             'staging_storage_id': args.staging_storage, 'bridge_id': args.bridge}
            if args.stage == 'show':
                return image_build_workflow.show(app, vmid=args.vmid, node=args.node, configuration=configuration)
            return image_build_workflow.plan(app, vmid=args.vmid, node=args.node, configuration=configuration,
                confirmation=args.confirmation, acknowledged=args.ack_image_build, request_id=args.request_id, review_file=args.review_file)
        if args.action == 'template':
            from . import template_workflow
            if args.stage == 'show':
                return template_workflow.show(app, args.vmid, args.node)
            if args.stage == 'plan':
                return template_workflow.plan(app, vmid=args.vmid, node=args.node, confirmation=args.confirmation,
                    conversion_acknowledged=args.ack_conversion, guest_prepared=args.guest_prepared, request_id=args.request_id, review_file=args.review_file)
            return template_workflow.execute(app, args.review_file, lambda value: confirm_change(value, args.yes))
        if args.action == 'clone':
            from . import clone_workflow
            if args.stage == 'show':
                return clone_workflow.show(app, args.vmid, args.node, args.new_vmid, args.storage)
            if args.stage == 'plan':
                return clone_workflow.plan(app, vmid=args.vmid, node=args.node, new_vmid=args.new_vmid, name=args.name,
                    storage=args.storage, request_id=args.request_id, review_file=args.review_file,
                    ack_guest_identity=args.ack_guest_identity)
            return clone_workflow.execute(app, args.review_file, lambda value: confirm_change(value, args.yes))
        if args.action == 'network':
            from . import network_workflow
            if args.stage == 'show':
                return network_workflow.show(app, args.vmid, args.node)
            if args.stage == 'plan':
                return network_workflow.plan(app, vmid=args.vmid, node=args.node, bridge_id=args.bridge,
                    vlan_tag=args.vlan_tag, request_id=args.request_id, review_file=args.review_file)
            return network_workflow.execute(app, args.review_file, lambda value: confirm_change(value, args.yes))
        if args.action == 'disk':
            from . import disk_workflow
            if args.stage == 'show':
                return disk_workflow.show(app, args.vmid, args.node)
            if args.stage == 'plan':
                return disk_workflow.plan(app, vmid=args.vmid, node=args.node, size_gib=args.size_gib,
                    request_id=args.request_id, review_file=args.review_file)
            return disk_workflow.execute(app, args.review_file, lambda value: confirm_change(value, args.yes))
        if args.stage == 'plan':
            return workflows.create_plan(app, args.file, args.request_id, args.review_file)
        return workflows.create_execute(app, args.review_file, args.ack_yellow,
                                        lambda value: confirm_change(value, args.yes))
    if args.command == 'proxmox-setup':
        from .proxmox_setup import wizard, simple_wizard
        from .output import text
        if not args.list and not args.advanced:
            return simple_wizard(app, read=prompt, password=secure_password,
                output=lambda message: print(text(message), file=sys.stderr), attempt_id=args.resume)
        return app.proxmox_setup('list') if args.list else wizard(
            app, read=prompt, password=secure_password,
            output=lambda message: print(text(message), file=sys.stderr), attempt_id=args.resume,
            include_compute=True, include_create=True, include_disk=True, include_network=True, include_clone=True, include_delete=True, include_console=True, include_template=True, include_image_build=True, include_image_cleanup=True, include_backup=True, include_restore=True, include_migrate=True, include_host_storage=True, include_host_network=True)
    raise ClientError('INVALID_COMMAND', '지원하지 않는 명령입니다.', 2)


def main(argv=None, *, session_store=None, in_shell=False):
    from .output import emit
    raw = list(sys.argv[1:] if argv is None else argv)
    as_json = '--json' in raw or ('--human' not in raw and not sys.stdout.isatty())
    try:
        argparser = parser()
        args = argparser.parse_args(raw)
        if args.command is None:
            argparser.print_help()
            return 0
        args.config_dir = getattr(args, 'config_dir', Path(os.getenv('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'gjallar')
        args.session_mode = getattr(args, 'session_mode', 'keyring')
        args.connection = getattr(args, 'connection', None)
        if args.command == 'tui' and args.connection:
            raise ClientError('INVALID_ARGUMENT', 'TUI에서는 화면의 저장된 서버 목록에서 연결을 선택하세요.', 2)
        if in_shell and args.command in {'shell', 'tui'}:
            raise ClientError('INVALID_COMMAND', 'shell 안에서는 CLI 명령을 사용하고 종료하려면 exit를 입력하세요.', 2)
        if in_shell and session_store is not None and args.session_mode != session_store.mode:
            raise ClientError('INVALID_SESSION_MODE', 'session 모드를 바꾸려면 shell을 종료한 뒤 다시 실행하세요.', 2)
        connections = Connections(args.config_dir)
        if args.command == 'connect':
            connections.add(args.name, args.origin, args.cookie_name, args.ca_file)
            result = {'ok': True, 'message': '서버 주소를 저장했습니다. 아직 로그인하거나 연결을 검증하지 않았습니다.',
                      'next': f'gjallar login --connection {args.name}'}
        elif args.command == 'connection' and args.action == 'list':
            result = {'ok': True, **connections.read()}
        elif args.command in {'service', 'upgrade', 'bootstrap'}:
            from .bootstrap import Bootstrap
            bootstrap = Bootstrap(args.install_dir)
            if args.command == 'bootstrap':
                result = bootstrap.install(image=args.image, port=args.port, administrator=administrator, bind_address=args.bind_address)
                origin = result['url']
                name = 'local-' + origin.rsplit(':', 1)[-1]
                profiles = connections.read()['connections']
                if name not in profiles:
                    connections.add(name, origin)
                elif profiles[name]['origin'] != origin:
                    raise ClientError('CONNECTION_CONFLICT', '설치는 완료했지만 local 별칭이 다른 주소입니다. connect로 새 별칭을 저장하세요.', 2)
                result['next'] = f'gjallar login --connection {name} (설치 시 만든 계정)'
            else:
                result = bootstrap.service(args.action) if args.command == 'service' else bootstrap.upgrade(args.image)
        elif args.command == 'vm' and args.action == 'create' and args.stage == 'example':
            from .workflows import EXAMPLE
            print(json.dumps(EXAMPLE, ensure_ascii=True, indent=2))
            return 0
        else:
            sessions = session_store if session_store is not None else (MemoryStore() if args.session_mode == 'memory' else KeyringStore())
            app = Application(connections, sessions, connection_name=args.connection)
            if args.command == 'tui':
                return tui.run(app, local_start=local_start)
            if args.command == 'shell':
                return shell(args, connections, sessions)
            if args.session_mode == 'memory' and not in_shell:
                print('memory session은 명령 종료 시 사라집니다. 연속 사용: gjallar --session-mode memory shell', file=sys.stderr)
            result = execute(args, app)
        emit(result, as_json=as_json, stream=sys.stdout)
        return result.get('exit_code', 0)
    except ClientError as exc:
        emit(exc.output(), as_json=as_json, stream=sys.stdout if as_json else sys.stderr)
        return exc.exit_code
    except (KeyboardInterrupt, EOFError):
        emit(ClientError('INTERRUPTED', '중단됐습니다. 실행 요청을 보냈다면 Operations에서 결과를 먼저 확인하세요.', 130).output(),
             as_json=as_json, stream=sys.stdout if as_json else sys.stderr)
        return 130
    except OSError:
        emit(ClientError('LOCAL_IO_FAILED', '로컬 파일 또는 입력을 사용할 수 없습니다.').output(),
             as_json=as_json, stream=sys.stdout if as_json else sys.stderr)
        return 7


if __name__ == '__main__':
    raise SystemExit(main())
