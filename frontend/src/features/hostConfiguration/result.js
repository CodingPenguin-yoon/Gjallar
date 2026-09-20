const ordered = value => Array.isArray(value) ? value.map(ordered) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])])) : value
export const sameConfiguration = (left, right) => JSON.stringify(ordered(left)) === JSON.stringify(ordered(right))

function verifiedResult(observed) {
  const operation = observed.operation
  return {...operation, verified: operation.status === 'succeeded'
    && !operation.coordination_incomplete && !observed.coordination_incomplete}
}

export function assertStorageResult(observed, operationId, target, requested) {
  const operation = observed?.operation
  if (!operationId || operation?.operation_id !== operationId || operation.operation_type !== 'host_storage'
      || operation.target_type !== 'proxmox_storage' || operation.target_id !== `storage:${target.storage_id}`
      || !sameConfiguration(operation.details?.target, target) || !sameConfiguration(operation.details?.requested, requested)) {
    throw new Error('작업 결과가 검토한 storage 대상·종류·요청과 다릅니다.')
  }
  return verifiedResult(observed)
}

export function assertBridgeResult(observed, operationId, target, requested) {
  const operation = observed?.operation
  if (!operationId || operation?.operation_id !== operationId || operation.operation_type !== 'host_network'
      || operation.target_type !== 'proxmox_network' || operation.target_id !== `node:${target.node_id}/bridge:${target.bridge_id}`
      || !sameConfiguration(operation.details?.target, target) || !sameConfiguration(operation.details?.requested, requested)) {
    throw new Error('작업 결과가 검토한 bridge 대상·종류·요청과 다릅니다.')
  }
  return verifiedResult(observed)
}

export function normalizeVlanIds(value) {
  if (typeof value !== 'string' || !value.trim() || value.length > 1024) throw new Error('VLAN 목록을 입력하세요.')
  const values = new Set()
  for (const part of value.trim().split(/\s+/)) {
    if (!/^[1-9][0-9]{0,3}(-[1-9][0-9]{0,3})?$/.test(part)) throw new Error('VLAN은 공백으로 구분한 1~4094 ID 또는 범위여야 합니다.')
    const bounds = part.split('-').map(Number)
    const first = bounds[0], last = bounds.at(-1)
    if (first > last || last > 4094) throw new Error('VLAN 범위는 1~4094여야 합니다.')
    for (let number = first; number <= last; number++) values.add(number)
  }
  const ordered = [...values].sort((a, b) => a - b)
  const groups = []
  let first = ordered[0], last = first
  for (const number of ordered.slice(1)) {
    if (number === last + 1) last = number
    else {groups.push(first === last ? `${first}` : `${first}-${last}`); first = last = number}
  }
  groups.push(first === last ? `${first}` : `${first}-${last}`)
  return groups.join(' ')
}
