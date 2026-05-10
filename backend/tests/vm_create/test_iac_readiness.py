"""Tests for Create VM IaC root readiness checks."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class VmCreateIacReadinessTests(unittest.TestCase):
    def test_readiness_uses_iac_folder_and_state_sibling_from_shared_root(self):
        from app.vm_create.paths import iac_path_context

        with tempfile.TemporaryDirectory() as temp_root:
            shared_root = Path(temp_root) / "nfs"
            shared_root.mkdir()
            with patch.dict(
                "os.environ",
                {
                    "GJALLAR_SHARED_ROOT": str(shared_root),
                    "GJALLAR_IAC_ROOT": "",
                    "GJALLAR_TF_STATE_ROOT": "",
                    "GJALLAR_TERRAFORM_STATE_ROOT": "",
                },
                clear=False,
            ):
                context = iac_path_context()

        self.assertEqual(str(shared_root / "IaC"), context["iac_root"])
        self.assertEqual(str(shared_root / "IaC-state" / "gjallar"), context["terraform_state_root"])

    def test_readiness_reports_plan_ready_without_git_and_execute_blocked(self):
        from app.vm_create.iac_readiness import run_iac_readiness

        with tempfile.TemporaryDirectory() as temp_root:
            shared_root = Path(temp_root) / "nfs"
            (shared_root / "IaC").mkdir(parents=True)
            (shared_root / "IaC-state" / "gjallar").mkdir(parents=True)
            with patch.dict("os.environ", {"GJALLAR_SHARED_ROOT": str(shared_root)}, clear=False):
                result = run_iac_readiness()

        self.assertTrue(result.ready_for_plan)
        self.assertFalse(result.ready_for_execute)
        self.assertEqual("yellow", result.risk_level)
        self.assertIn("iac_git_repo_missing", {risk.code for risk in result.risks})
        self.assertEqual([], result.side_effects)

    def test_readiness_is_green_when_iac_root_state_and_git_marker_exist(self):
        from app.vm_create.iac_readiness import run_iac_readiness

        with tempfile.TemporaryDirectory() as temp_root:
            shared_root = Path(temp_root) / "nfs"
            (shared_root / "IaC" / ".git").mkdir(parents=True)
            (shared_root / "IaC" / "manifests" / "vms").mkdir(parents=True)
            (shared_root / "IaC" / "generated").mkdir(parents=True)
            (shared_root / "IaC-state" / "gjallar").mkdir(parents=True)
            with patch.dict("os.environ", {"GJALLAR_SHARED_ROOT": str(shared_root)}, clear=False):
                result = run_iac_readiness()

        self.assertTrue(result.ready_for_plan)
        self.assertTrue(result.ready_for_execute)
        self.assertEqual("green", result.risk_level)
        self.assertEqual([], result.risks)

    def test_missing_iac_root_is_red(self):
        from app.vm_create.iac_readiness import run_iac_readiness

        with tempfile.TemporaryDirectory() as temp_root:
            shared_root = Path(temp_root) / "nfs"
            shared_root.mkdir()
            (shared_root / "IaC-state" / "gjallar").mkdir(parents=True)
            with patch.dict("os.environ", {"GJALLAR_SHARED_ROOT": str(shared_root)}, clear=False):
                result = run_iac_readiness()

        self.assertFalse(result.ready_for_plan)
        self.assertFalse(result.ready_for_execute)
        self.assertEqual("red", result.risk_level)
        self.assertIn("iac_root_missing", {risk.code for risk in result.risks})


if __name__ == "__main__":
    unittest.main()
