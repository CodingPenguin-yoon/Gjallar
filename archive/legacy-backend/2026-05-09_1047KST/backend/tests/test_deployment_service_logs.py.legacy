import unittest

from app.domains.deploy.service import DeploymentService
from app.shared.tasks import task_manager


class FakeTerraformService:
    def init(self, task_id):
        return True, None

    def select_or_create_workspace(self, task_id, workspace):
        return True, workspace

    def plan(self, task_id, workspace=None):
        return True, None

    def apply(self, task_id, auto_approve=True, variables=None, workspace=None):
        return True, None

    def get_output(self, workspace=None):
        return {"vm_id": 101, "vm_name": "new-vm", "vm_ip": None}


class FakeAnsibleService:
    def __init__(self):
        self.called = False

    def run_playbook(self, *args, **kwargs):
        self.called = True
        return True, None


class FakeProxmoxService:
    pass


class DeploymentServiceLogTest(unittest.TestCase):
    def test_missing_ip_is_logged_as_ip_discovery_pending_before_ansible_skip(self):
        task_id = "test-provisioning-log-missing-ip"
        task_manager.clear_task(task_id)
        task_manager.create_task(task_id, metadata={"action": "provision"})
        service = DeploymentService()
        service.terraform_service = FakeTerraformService()
        service.ansible_service = FakeAnsibleService()
        service.proxmox_service = FakeProxmoxService()

        service._execute_deployment(
            task_id,
            skip_terraform=False,
            skip_ansible=False,
            deploy_request={
                "server_name": "new-vm",
                "server_id": "pve1",
                "template_id": "pve1/9000",
                "storage_id": "local-lvm",
                "network_ids": ["vmbr0"],
                "disk_size_gb": 50,
            },
        )

        logs = "\n".join(task_manager.get_logs(task_id))
        self.assertIn("Provisioning boundary", logs)
        self.assertIn("IP discovery pending", logs)
        self.assertIn("Ansible skipped because VM IP is missing", logs)
        self.assertFalse(service.ansible_service.called)
        task_manager.clear_task(task_id)


if __name__ == "__main__":
    unittest.main()
