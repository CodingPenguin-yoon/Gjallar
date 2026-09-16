"""Token-authenticated Proxmox tasks retain their pollable locator."""
import pytest
from app.operations.core.evidence import compact_proxmox_task


def test_api_token_task_locator_is_preserved():
    upid = 'UPID:node:000001:000002:000003:qmclone:118:operator@pve!test-token:'
    assert compact_proxmox_task({}, node='node', upid=upid)['upid'] == upid


@pytest.mark.parametrize('suffix', ['?secret=x', '/other', '\nheader:x', '#fragment', ' '])
def test_task_locator_still_rejects_path_and_query_injection(suffix):
    upid = 'UPID:node:operator@pve!token:' + suffix + ':'
    assert compact_proxmox_task({}, upid=upid)['upid'] == ''
