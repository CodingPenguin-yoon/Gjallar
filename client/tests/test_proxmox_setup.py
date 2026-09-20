import json

from gjallar_client.proxmox_setup import wizard


class SetupServer:
    def __init__(self, phase):
        self.row = {"attempt_id": "example-attempt", "phase": phase, "version": 3, "mode": "issue"}
        self.calls = []

    def proxmox_setup(self, action, *, attempt_id=None, body=None):
        self.calls.append((action, body))
        if body:
            assert body["expected_version"] == self.row["version"]
        if action == "login":
            self.row = {**self.row, "version": self.row["version"] + 1, "mfa_required": True}
        elif action == "mfa":
            assert body["otp"] == "123456"
            self.row = {**self.row, "version": self.row["version"] + 1, "mfa_required": False}
        elif action == "observe":
            self.row = {**self.row, "token_exists": True, "automatic_retry_allowed": False}
        elif action == "revoke":
            assert body["token_id"] == "test@pve!gjallar-example-attempt"
            self.row = {**self.row, "version": self.row["version"] + 1, "phase": "revoked"}
        return {"data": dict(self.row)}


def test_resume_observes_unknown_issue_without_reissuing():
    app = SetupServer("token_dispatching")
    inputs = iter(["observe"])
    secrets = iter(["", "synthetic-password", "123456"])
    output = []
    result = wizard(app, read=lambda _: next(inputs), password=lambda _: next(secrets),
                    output=output.append, attempt_id="example-attempt")
    assert [action for action, _ in app.calls] == ["status", "login", "mfa", "observe"]
    assert result["data"]["phase"] == "token_dispatching"
    assert "synthetic-password" not in json.dumps(result) + "".join(output)


def test_resume_revoke_requires_exact_user_input():
    app = SetupServer("revocation_pending")
    inputs = iter(["revoke", "test@pve!gjallar-example-attempt"])
    secrets = iter(["", "synthetic-password", "123456"])
    result = wizard(app, read=lambda _: next(inputs), password=lambda _: next(secrets),
                    output=lambda _: None, attempt_id="example-attempt")
    assert [action for action, _ in app.calls] == ["status", "login", "mfa", "observe", "revoke"]
    assert result["data"]["phase"] == "revoked"


def test_resume_does_not_revoke_on_empty_confirmation():
    app = SetupServer("active")
    inputs = iter(["revoke", ""])
    secrets = iter(["", "synthetic-password", "123456"])
    wizard(app, read=lambda _: next(inputs), password=lambda _: next(secrets),
           output=lambda _: None, attempt_id="example-attempt")
    assert all(action != "revoke" for action, _ in app.calls)


def test_cli_compute_is_explicit_and_tui_keeps_original_questions():
    for include_compute in (False, True):
        captured = []

        class PrepareOnly:
            def proxmox_setup(self, action, *, body):
                captured.append(body)
                return {"data": {"attempt_id": "synthetic", "phase": "cancelled"}}

        inputs = iter(["", "https://pve.example.test", "test@pve", "", "node1", "101", "", "", "", "yes"])
        wizard(PrepareOnly(), read=lambda _: next(inputs), password=lambda _: "", output=lambda _: None,
               include_compute=include_compute)
        assert captured[0]["intent"]["features"] == (["read", "compute"] if include_compute else ["read"])


def test_cli_creation_scope_and_guest_permission_are_reviewed():
    captured, output = [], []

    class PrepareOnly:
        def proxmox_setup(self, action, *, body):
            captured.append(body)
            return {"data": {"attempt_id": "synthetic", "phase": "cancelled"}}

    inputs = iter(["", "https://pve.example.test", "test@pve", "", "node1", "101", "store1", "vmbr0",
                   "", "", "yes", "9000", "40000,40001"])
    wizard(PrepareOnly(), read=lambda _: next(inputs), password=lambda _: "", output=output.append,
           include_compute=True, include_create=True)
    intent = captured[0]["intent"]
    assert intent["features"] == ["read", "create"]
    assert intent["scope"]["template_vmids"] == [9000]
    assert intent["scope"]["create_vmids"] == [40000, 40001]
    assert any("PVE token" in line for line in output)


def test_image_build_registration_separates_future_ids_without_changing_tui():
    for enabled in (False, True):
        captured, output = [], []

        class PrepareOnly:
            def proxmox_setup(self, action, *, body):
                captured.append(body)
                return {"data": {"attempt_id": "synthetic", "phase": "cancelled"}}

        inputs = iter(["", "https://pve.example.test", "test@pve", "", "node1", "101", "store1", "vmbr0", "", "yes", "40004,40005"])
        wizard(PrepareOnly(), read=lambda _: next(inputs), password=lambda _: "", output=output.append,
               include_image_build=enabled)
        intent = captured[0]['intent']
        assert intent['features'] == (['read', 'image_build'] if enabled else ['read'])
        assert intent['scope'].get('image_vmids', []) == ([40004, 40005] if enabled else [])
        assert any('업로드' in line for line in output) is enabled


def test_cleanup_registration_requires_selected_storage_scope_and_warns_about_privilege():
    captured, output = [], []
    class PrepareOnly:
        def proxmox_setup(self, action, *, body):
            captured.append(body)
            return {'data': {'attempt_id': 'synthetic', 'phase': 'cancelled'}}
    inputs = iter(['', 'https://pve.example.test', 'test@pve', '', 'node1', '40000', 'stage,target', '', '', 'yes', 'stage'])
    wizard(PrepareOnly(), read=lambda _: next(inputs), password=lambda _: '', output=output.append, include_image_cleanup=True)
    intent = captured[0]['intent']
    assert intent['features'] == ['read', 'image_cleanup']
    assert intent['scope']['image_cleanup_storages'] == ['stage']
    assert any('Datastore.Allocate' in line for line in output)


def test_backup_scope_is_opt_in_without_changing_tui_defaults():
    for enabled in (False, True):
        captured = []
        class PrepareOnly:
            def proxmox_setup(self, action, *, body):
                captured.append(body)
                return {'data': {'attempt_id': 'synthetic', 'phase': 'cancelled'}}
        inputs = iter(['', 'https://pve.example.test', 'test@pve', '', 'node1', '40000', 'source,backup', '', '', 'yes', 'backup'])
        wizard(PrepareOnly(), read=lambda _: next(inputs), password=lambda _: '', output=lambda _: None, include_backup=enabled)
        intent = captured[0]['intent']
        assert intent['features'] == (['read','backup'] if enabled else ['read'])
        assert intent['scope'].get('backup_storages',[]) == (['backup'] if enabled else [])


def test_restore_scope_is_separate_and_does_not_require_backup_creation():
    captured=[]
    class PrepareOnly:
        def proxmox_setup(self,action,*,body):
            captured.append(body)
            return {'data':{'attempt_id':'synthetic','phase':'cancelled'}}
    inputs=iter(['','https://pve.example.test','test@pve','','node1','40000','nfs,target','vmbr1','','yes','nfs','40006','target'])
    wizard(PrepareOnly(),read=lambda _:next(inputs),password=lambda _:'',output=lambda _:None,include_restore=True)
    intent=captured[0]['intent']
    assert intent['features']==['read','restore']
    assert intent['scope']['restore_vmids']==[40006]
    assert intent['scope']['restore_storages']==['target'] and intent['scope']['backup_storages']==['nfs']


def test_migration_scope_is_opt_in_and_keeps_tui_questions():
    for enabled in (False, True):
        captured, output = [], []
        class PrepareOnly:
            def proxmox_setup(self, action, *, body):
                captured.append(body)
                return {'data': {'attempt_id': 'synthetic', 'phase': 'cancelled'}}
        inputs = iter(['', 'https://pve.example.test', 'test@pve', '', 'node1,node2', '40000', 'nfs', 'vmbr1', '', 'yes'])
        wizard(PrepareOnly(), read=lambda _: next(inputs), password=lambda _: '', output=output.append, include_migrate=enabled)
        intent = captured[0]['intent']
        assert intent['features'] == (['read', 'migrate'] if enabled else ['read'])
        assert intent['scope']['nodes'] == ['node1', 'node2']
        assert any('VM.Migrate' in value for value in output) is enabled


def test_host_storage_scope_is_opt_in_and_tui_default_stays_unchanged():
    for enabled in (False,True):
        captured,output=[],[]
        class PrepareOnly:
            def proxmox_setup(self,action,*,body):
                captured.append(body)
                return {'data':{'attempt_id':'synthetic','phase':'cancelled'}}
        inputs=iter(['','https://pve.example.test','test@pve','','node1','','','','','yes','new-dir'])
        wizard(PrepareOnly(),read=lambda _:next(inputs),password=lambda _:'',output=output.append,include_host_storage=enabled)
        intent=captured[0]['intent']
        assert intent['features']==(['read','host_storage'] if enabled else ['read'])
        assert intent['scope'].get('host_storages',[])==(['new-dir'] if enabled else [])
        assert any('/storage의 Datastore.Allocate' in line for line in output) is enabled


def test_host_network_scope_is_opt_in_and_tui_default_stays_unchanged():
    for enabled in (False,True):
        captured,output=[],[]
        class PrepareOnly:
            def proxmox_setup(self,action,*,body):
                captured.append(body)
                return {'data':{'attempt_id':'synthetic','phase':'cancelled'}}
        inputs=iter(['','https://pve.example.test','test@pve','','node1','','','','','yes','vmbr40'])
        wizard(PrepareOnly(),read=lambda _:next(inputs),password=lambda _:'',output=output.append,include_host_network=enabled)
        intent=captured[0]['intent']
        assert intent['features']==(['read','host_network'] if enabled else ['read'])
        assert intent['scope'].get('host_bridges',[])==(['vmbr40'] if enabled else [])
        assert any('Sys.Modify' in line for line in output) is enabled
