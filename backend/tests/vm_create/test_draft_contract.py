"""RED tests for create-VM draft defaults and allowed profile surface."""

import unittest


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
