"""RED tests for create-VM draft defaults and allowed profile surface."""

import unittest
from unittest.mock import patch


class VmCreateDraftContractTests(unittest.TestCase):
    def _build_default_draft(self):
        try:
            from app.vm_create.drafts import build_default_vm_draft
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.vm_create.drafts.build_default_vm_draft for the Create VM "
                f"wizard contract, but it is missing: {exc}"
            )
        return build_default_vm_draft(operator_id="test-operator")

    def test_default_draft_uses_general_vm_profile(self):
        draft = self._build_default_draft()
        self.assertEqual("general-vm", draft.profile_id)
        self.assertEqual(2, draft.hardware.cpu)
        self.assertEqual(4096, draft.hardware.memory_mb)
        self.assertEqual(40, draft.hardware.disk_gb)
        self.assertEqual("static", draft.network.ip_mode)
        self.assertEqual("yoon", draft.access.cloud_init_user)
        self.assertFalse(draft.access.password_login)

    def test_default_draft_accepts_resolved_inventory_vmid(self):
        from app.vm_create.drafts import build_default_vm_draft

        draft = build_default_vm_draft(operator_id="test-operator", proposed_vmid=303)

        self.assertEqual(303, draft.proposed_vmid)

    def test_draft_preserves_selected_template_and_bridge(self):
        from app.vm_create.drafts import build_default_vm_draft

        draft = build_default_vm_draft(
            operator_id="test-operator",
            storage_id="nas-server",
            template_id="ubuntu-template",
            template_vmid=9000,
            template_node_id="yoonmanserver2",
            network_id="server-net",
            bridge_id="vmbr0",
        )

        self.assertEqual("nas-server", draft.storage_id)
        self.assertEqual("ubuntu-template", draft.template_id)
        self.assertEqual(9000, draft.template_vmid)
        self.assertEqual("yoonmanserver2", draft.template_node_id)
        self.assertEqual("server-net", draft.network.network_id)
        self.assertEqual("vmbr0", draft.network.bridge_id)

    def test_iac_state_path_can_be_relocated_with_environment(self):
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.paths import iac_path_context

        with patch.dict(
            "os.environ",
            {
                "GJALLAR_SHARED_ROOT": "/Users/yoon/mnt/nfs",
                "GJALLAR_IAC_ROOT": "",
                "GJALLAR_TF_STATE_ROOT": "",
                "GJALLAR_TERRAFORM_STATE_ROOT": "",
            },
            clear=False,
        ):
            draft = build_default_vm_draft(operator_id="test-operator", job_id="job-env-root")
            context = iac_path_context()

        self.assertEqual("/Users/yoon/mnt/nfs/IaC", context["iac_root"])
        self.assertEqual("/Users/yoon/mnt/nfs/IaC-state/gjallar", context["terraform_state_root"])
        self.assertEqual(
            "/Users/yoon/mnt/nfs/IaC-state/gjallar/vm-job-env-root/terraform.tfstate",
            draft.terraform_state_path,
        )

    def test_explicit_iac_and_state_roots_override_shared_root(self):
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.paths import iac_path_context

        with patch.dict(
            "os.environ",
            {
                "GJALLAR_SHARED_ROOT": "/ignored/shared",
                "GJALLAR_IAC_ROOT": "~/mnt/nfs/IaC",
                "GJALLAR_TF_STATE_ROOT": "~/mnt/nfs/IaC-state/gjallar",
                "GJALLAR_TERRAFORM_STATE_ROOT": "",
            },
            clear=False,
        ):
            draft = build_default_vm_draft(operator_id="test-operator", job_id="job-explicit-root")
            context = iac_path_context()

        self.assertTrue(context["iac_root"].endswith("/mnt/nfs/IaC"))
        self.assertTrue(context["terraform_state_root"].endswith("/mnt/nfs/IaC-state/gjallar"))
        self.assertTrue(
            draft.terraform_state_path.endswith(
                "/mnt/nfs/IaC-state/gjallar/vm-job-explicit-root/terraform.tfstate"
            )
        )

    def test_explicit_iac_root_derives_state_sibling_when_state_root_is_not_set(self):
        from app.vm_create.paths import iac_path_context

        with patch.dict(
            "os.environ",
            {
                "GJALLAR_SHARED_ROOT": "/ignored/shared",
                "GJALLAR_IAC_ROOT": "/Users/yoon/mnt/nfs/IaC",
                "GJALLAR_TF_STATE_ROOT": "",
                "GJALLAR_TERRAFORM_STATE_ROOT": "",
            },
            clear=False,
        ):
            context = iac_path_context()

        self.assertEqual("/Users/yoon/mnt/nfs/IaC", context["iac_root"])
        self.assertEqual("/Users/yoon/mnt/nfs/IaC-state/gjallar", context["terraform_state_root"])

    def test_only_general_vm_is_create_enabled(self):
        try:
            from app.vm_create.drafts import list_create_profile_options
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.vm_create.drafts.list_create_profile_options for the Create VM "
                f"wizard contract, but it is missing: {exc}"
            )
        options = list_create_profile_options()
        enabled = [option.profile_id for option in options if option.create_enabled]
        self.assertEqual(["general-vm"], enabled)


if __name__ == "__main__":
    unittest.main()
