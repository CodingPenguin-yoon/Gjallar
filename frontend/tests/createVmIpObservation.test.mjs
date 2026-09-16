import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { renderToStaticMarkup } from 'react-dom/server'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'
import * as createVmFlow from '../src/utils/createVmFlow.js'

const source = readFileSync(new URL('../src/components/CreateInstanceWizard.jsx', import.meta.url), 'utf8')
const compiled = transformSync(source, { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const compiledModule = { exports: {} }
const localRequire = (specifier) => {
  if (specifier === 'react/jsx-runtime') return { jsx, jsxs, Fragment }
  if (specifier === '../utils/createVmFlow') return createVmFlow
  if (['react', 'react-router-dom', 'lucide-react', '../services/apiV1', '../utils/auth', '../utils/createVmDefaults'].includes(specifier)) return {}
  throw new Error(`Unexpected test import: ${specifier}`)
}
new vm.Script(`(function(require, module, exports) {${compiled}\n})`).runInThisContext()(localRequire, compiledModule, compiledModule.exports)
const { CreateVmPreflightCheck } = compiledModule.exports

const baseCheck = {
  code: 'static_ip_available',
  level: 'yellow',
  status: 'warn',
  detail: {
    static_ip: '192.168.2.149',
    result: 'unverified',
    conflicts: [],
    inventory: { status: 'no_conflict_observed', guest_agent_complete: false, failed_targets: ['node-a:101', 'node-a:900'] },
    ping: { status: 'no_reply', reason: 'no_echo_reply', source: 'icmp', execution_location: 'gjallar_backend' },
  },
}
const renderCheck = (check) => renderToStaticMarkup(jsx(CreateVmPreflightCheck, { check }))

let html = renderCheck(baseCheck)
assert.match(html, /기존 VM 정보:/)
assert.match(html, /확인한 기존 VM 정보에서 같은 IP를 찾지 못했습니다/)
assert.match(html, /IP를 읽지 못한 기존 VM: node-a:101, node-a:900/)
assert.match(html, /Ping 응답:/)
assert.match(html, /응답 없음 · 미사용 IP라는 뜻은 아닙니다/)
assert.match(html, /Gjallar 서버에서 확인/)
assert.match(html, /직접 확보한 IP인지 확인해주세요/)
assert.match(html, /bg-yellow-50/)
assert.doesNotMatch(html, /bg-green-50|>정상<|사용 가능|검증 성공/)

html = renderCheck({
  ...baseCheck,
  detail: { ...baseCheck.detail, inventory: { status: 'no_conflict_observed', guest_agent_complete: true, failed_targets: [] } },
})
assert.match(html, /bg-yellow-50/, 'Complete guest agent observation and ping silence must still need confirmation')
assert.doesNotMatch(html, /읽지 못한 기존 VM|bg-green-50/)

for (const [reason, message] of [
  ['ping_not_found', 'Ping 도구가 없어'],
  ['permission_denied', '실행할 권한이 없어'],
  ['unsupported_platform', '확인을 지원하지 않습니다'],
  ['process_timeout', '확인 시간이 초과되어'],
  ['execution_error', '실행에 실패해'],
  ['invalid_ipv4', '입력한 IP를 Ping으로 확인할 수 없습니다'],
  ['invalid_target', '입력한 IP는 Ping 확인 대상이 아닙니다'],
  ['unexpected-raw-error-text', 'Ping으로 사용 여부를 확인하지 못했습니다'],
  ['constructor', 'Ping으로 사용 여부를 확인하지 못했습니다'],
]) {
  html = renderCheck({
    ...baseCheck,
    detail: { ...baseCheck.detail, ping: { ...baseCheck.detail.ping, status: 'unavailable', reason } },
  })
  assert.ok(html.includes(message), `Unavailable reason ${reason} needs a clear explanation`)
  assert.match(html, /bg-yellow-50/)
  assert.doesNotMatch(html, /unexpected-raw-error-text|bg-green-50|사용 가능|검증 성공/)
}

html = renderCheck({
  ...baseCheck,
  level: 'red',
  status: 'fail',
  detail: { ...baseCheck.detail, result: 'in_use', ping: { ...baseCheck.detail.ping, status: 'reply', reason: 'echo_reply' } },
})
assert.match(html, /192.168.2.149의 사용이 확인되어 생성을 진행할 수 없습니다/)
assert.match(html, /응답 있음 · 해당 IP가 사용 중입니다/)
assert.match(html, /bg-red-50/)
assert.doesNotMatch(html, /직접 확보한 IP인지 확인해주세요/)

html = renderCheck({
  ...baseCheck,
  level: 'red',
  status: 'fail',
  detail: {
    ...baseCheck.detail,
    result: 'in_use',
    conflicts: [{ node_id: 'node-b', vmid: 102, name: 'app-server' }],
    inventory: { status: 'conflict', guest_agent_complete: true, failed_targets: [] },
  },
})
assert.match(html, /같은 IP를 사용하는 VM: node-b:102 \(app-server\)/)
assert.match(html, /응답 없음/, 'Known VM conflict must remain visible even when ping is silent')
assert.match(html, /bg-red-50/)

html = renderCheck({
  code: 'inventory_guest_agent_complete', level: 'yellow', status: 'warn', message: '기존 VM의 내부 IP 관찰이 불완전합니다.',
  detail: { failed_targets: ['node-a:101'] },
})
assert.match(html, /IP를 읽지 못한 기존 VM: node-a:101/)
assert.match(html, /기존 VM의 내부 IP 관찰이 불완전합니다/)
assert.doesNotMatch(html, /Ping 응답/, 'An inventory-only legacy response must not invent a ping result')

console.log('createVmIpObservation dual observation rendering exercised')
