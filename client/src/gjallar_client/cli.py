"""Local installation and service maintenance; product operations use the web."""
import argparse
import getpass
import json
from pathlib import Path
import sys
import unicodedata
import warnings

from .bootstrap import Bootstrap
from .errors import ClientError


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


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ClientError("INVALID_ARGUMENT", "설치·서비스 관리 명령만 지원합니다. VM 관리·로그인·Proxmox 연결은 웹을 사용하세요. --help로 명령을 확인하세요.", 2)


def parser():
    common = Parser(add_help=False, argument_default=argparse.SUPPRESS)
    output = common.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="JSON 한 개 출력")
    output.add_argument("--human", action="store_true", help="읽기 쉬운 출력")
    result = Parser(description="Gjallar · 로컬 설치와 서비스 관리", parents=[common],
                    epilog="로그인·VM 관리·Proxmox 연결은 웹에서 진행하세요.")
    commands = result.add_subparsers(dest="command")
    install = commands.add_parser("bootstrap", parents=[common], help="로컬 설치·시작 후 웹 주소 안내")
    install.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    install.add_argument("--image")
    install.add_argument("--port", type=int, default=8000)
    install.add_argument("--bind-address", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1", help="웹 공개 주소 (기본 loopback)")
    service = commands.add_parser("service", parents=[common], help="로컬 서비스 상태·시작·종료")
    service.add_argument("action", choices=["start", "status", "stop"])
    service.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    upgrade = commands.add_parser("upgrade", parents=[common], help="같은 DB schema의 이미지로 업그레이드")
    upgrade.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/gjallar")
    upgrade.add_argument("--image", required=True)
    return result


def emit(result, *, as_json, stream):
    if as_json:
        print(json.dumps(result, ensure_ascii=True), file=stream)
    else:
        for key, value in result.items():
            value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            safe = ''.join(c if unicodedata.category(c)[0] != 'C' else f'\\u{ord(c):04x}' for c in value)
            print(f'{key}: {safe}', file=stream)


def main(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    as_json = '--json' in raw or ('--human' not in raw and not sys.stdout.isatty())
    try:
        argparser = parser()
        args = argparser.parse_args(raw)
        if args.command is None:
            argparser.print_help()
            return 0
        bootstrap = Bootstrap(args.install_dir)
        if args.command == 'bootstrap':
            result = bootstrap.install(image=args.image, port=args.port, administrator=administrator, bind_address=args.bind_address)
            if result.get('bind_address') == '0.0.0.0':
                result['next'] = '브라우저에서 이 서버의 IP와 설치 port로 접속하고 최초 관리자 계정으로 로그인하세요.'
            else:
                result['next'] = '브라우저에서 url 주소를 열고 최초 관리자 계정으로 로그인하세요.'
        elif args.command == 'service':
            result = bootstrap.service(args.action)
        else:
            result = bootstrap.upgrade(args.image)
        emit(result, as_json=as_json, stream=sys.stdout)
        return 0
    except ClientError as exc:
        emit(exc.output(), as_json=as_json, stream=sys.stdout if as_json else sys.stderr)
        return exc.exit_code
    except (KeyboardInterrupt, EOFError):
        emit(ClientError('INTERRUPTED', '중단됐습니다. 설치 상태를 확인하고 같은 설치 경로로 다시 실행하세요.', 130).output(),
             as_json=as_json, stream=sys.stdout if as_json else sys.stderr)
        return 130
    except OSError:
        emit(ClientError('LOCAL_IO_FAILED', '로컬 파일 또는 입력을 사용할 수 없습니다.').output(),
             as_json=as_json, stream=sys.stdout if as_json else sys.stderr)
        return 7


if __name__ == '__main__':
    raise SystemExit(main())
