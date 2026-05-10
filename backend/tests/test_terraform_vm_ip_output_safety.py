import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TERRAFORM_MAIN = REPO_ROOT / "infra" / "terraform" / "main.tf"


class TerraformVmIpOutputSafetyTest(unittest.TestCase):
    def test_vm_ip_output_does_not_use_fixed_nested_ipv4_index(self):
        """DHCP/guest-agent IP lists can exist but be empty; avoid ipv4_addresses[1][0]."""
        source = TERRAFORM_MAIN.read_text()

        self.assertNotIn("ipv4_addresses[1][0]", source)
        self.assertIn("flatten(", source)
        self.assertIn("try(", source)

    def test_vm_apply_defaults_to_powered_off_and_explicit_vmid(self):
        source = TERRAFORM_MAIN.read_text()

        self.assertIn('variable "vm_id"', source)
        self.assertIn("vm_id     = var.vm_id > 0 ? var.vm_id : null", source)
        self.assertIn('variable "start_on_create"', source)
        self.assertIn("default     = false", source)
        self.assertIn("started = var.start_on_create", source)
        self.assertIn("on_boot = var.on_boot", source)
        self.assertNotIn("started = true", source)


if __name__ == "__main__":
    unittest.main()
