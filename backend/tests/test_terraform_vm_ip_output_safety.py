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


if __name__ == "__main__":
    unittest.main()
