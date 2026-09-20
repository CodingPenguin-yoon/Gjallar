// Canonical read must describe the same submitted operation, never a different success.
export function assertChangeResult(observed, operationId, expected) {
  const operation = observed?.operation
  if (!operationId || operation?.operation_id !== operationId) throw new Error('작업 결과 ID가 실행 응답과 다릅니다.')
  if (expected && (operation.operation_type !== expected.type || operation.target_type !== 'proxmox_vm'
      || operation.target_id !== `vmid:${expected.vmid}` || operation.details?.target?.node_id !== expected.node
      || operation.details?.target?.vmid !== Number(expected.vmid)
      || !Object.entries(expected.requested).every(([key, value]) => operation.details?.requested?.[key] === value))) {
    throw new Error('작업 결과가 검토한 대상·종류·요청과 다릅니다.')
  }
  return operation
}
