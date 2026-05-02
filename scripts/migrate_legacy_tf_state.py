#!/usr/bin/env python3
"""
legacy Terraform state를 infra/terraform workspace로 이관하는 유틸리티.

기본 source:
- backend/iac/terraform/terraform.tfstate

기본 target:
- infra/terraform (workspace 지정 필수)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate legacy local terraform state into infra workspace.",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="대상 Terraform workspace 이름",
    )
    parser.add_argument(
        "--legacy-dir",
        default=None,
        help="legacy terraform 디렉토리 경로 (기본: backend/iac/terraform)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="target workspace state가 있어도 강제 push",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    backend_path = repo_root / "backend"
    sys.path.insert(0, str(backend_path))

    try:
        from app.services.terraform import TerraformService
    except Exception as e:
        print(f"[ERROR] TerraformService import 실패: {e}")
        return 1

    service = TerraformService()
    ok, message = service.migrate_legacy_local_state(
        workspace=args.workspace,
        legacy_terraform_dir=args.legacy_dir,
        force=args.force,
    )
    if ok:
        print(f"[OK] {message}")
        return 0

    print(f"[ERROR] {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
