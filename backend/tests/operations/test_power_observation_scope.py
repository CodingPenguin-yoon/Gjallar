"""Power admission depends on the target, never aggregate optional coverage."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.proxmox.inventory import FakeProxmoxInventoryAdapter
from app.proxmox.models import InventoryAvailability, InventorySourceAvailability
from app.workloads.inventory import WorkloadInventoryQuery, WorkloadInventoryUnavailableError


def query_with_failure(source, failed_targets):
    snapshot = replace(FakeProxmoxInventoryAdapter().snapshot(), source='live_read_only',
                       availability=InventoryAvailability(sources=(InventorySourceAvailability(
                           source=source, expected_targets=2, observed_targets=1,
                           failed_targets=failed_targets),)))
    adapter = Mock(source='live_read_only', is_test_fixture=False)
    adapter.fresh_snapshot.return_value = snapshot
    adapter.snapshot.side_effect = AssertionError('Power requests must use a fresh observation')
    return WorkloadInventoryQuery(adapter), adapter


@pytest.mark.parametrize('source,failed', [
    ('guest_agent', ('node:101',)), ('storage', ('node',)), ('network', ('node',)),
    ('vm_config', ('node:102',)), ('vm_detail', ('node:102',)),
])
def test_unrelated_failures_do_not_block_power(source, failed):
    query, adapter = query_with_failure(source, failed)
    observed = query.require_mutation_adapter(node_id='node', vmid=101)
    assert not observed.snapshot().availability.complete
    adapter.fresh_snapshot.assert_called_once_with()


@pytest.mark.parametrize('source', ['vm_config', 'vm_detail'])
@pytest.mark.parametrize('failed', [('node:101',), ()])
def test_target_or_unattributed_required_failure_blocks_power(source, failed):
    query, _ = query_with_failure(source, failed)
    with pytest.raises(WorkloadInventoryUnavailableError) as error:
        query.require_mutation_adapter(node_id='node', vmid=101)
    detail = error.value.to_detail()
    assert detail['code'] == 'PROXMOX_VM_OBSERVATION_UNAVAILABLE'
    assert detail['target'] == 'node:101'
    assert detail['source'] == source
    assert detail['side_effects'] == []


def test_connection_failure_blocks_power():
    query, adapter = query_with_failure('guest_agent', ())
    adapter.fresh_snapshot.side_effect = RuntimeError('unreachable')
    with pytest.raises(WorkloadInventoryUnavailableError):
        query.require_mutation_adapter(node_id='node', vmid=101)
