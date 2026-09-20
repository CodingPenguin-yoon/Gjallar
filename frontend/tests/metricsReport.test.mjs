import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { transformSync } from 'esbuild'
import vm from 'node:vm'
import { metricsTargetMatches } from '../src/features/monitoring/model.js'

let state, previousDeps, cleanup, effect
const requests = []
const hooks = {
  useState(initial) { if (!state) state = initial; return [state, next => { state = next }] },
  useEffect(next, deps) {
    if (!previousDeps || deps.some((value, index) => value !== previousDeps[index])) { effect = next; previousDeps = deps }
  },
}
const api = {getMetrics: (...args) => new Promise((resolve, reject) => requests.push({args, resolve, reject}))}
const module = {exports: {}}
const source = readFileSync(new URL('../src/features/monitoring/useMetricsReport.js', import.meta.url), 'utf8')
const compiled = transformSync(source, {format: 'cjs'}).code
new vm.Script(`(function(require,module,exports){${compiled}})`).runInThisContext()(name => {
  if (name === 'react') return hooks
  if (name === '../../shared/api/apiV1') return {apiV1Client: api}
  if (name === './model') return {metricsTargetMatches}
  throw new Error(name)
}, module, module.exports)
const render = (...args) => {
  const value = module.exports.default(...args)
  if (effect) { cleanup?.(); cleanup = effect(); effect = null }
  return value
}
const flush = async () => { await Promise.resolve(); await Promise.resolve() }
const response = (node, timeframe = 'hour') => ({target: {kind:'node',node_id:node},timeframe})
assert.equal(render('node','a','','hour').busy, true)
assert.equal(render('node','b','','hour').report, null)
requests[0].resolve(response('a')); await flush()
assert.equal(render('node','b','','hour').report, null, 'Late old-node response must not appear under the new node')
requests[1].resolve(response('b')); await flush()
assert.equal(render('node','b','','hour').report.target.node_id, 'b')
assert.equal(render('node','b','','day').report, null, 'Old-period report must clear before the next request completes')
requests[2].resolve(response('b','hour')); await flush()
assert.match(render('node','b','','day').error, /기간/)
render('node','b','','day',1)
requests[3].reject(new Error('permission denied')); await flush()
assert.equal(render('node','b','','day',1).report, null)
assert.equal(render('node','b','','day',1).error, 'permission denied')
render('node','b','','day',2)
render('node','','','hour')
requests[4].resolve(response('b','day')); await flush()
assert.equal(render('node','','','hour').report, null, 'Clearing the selection must cancel pending state updates')
assert.equal(requests.length, 5, 'No node means no metrics request')
console.log('metrics request identity, late responses, errors and empty selection verified')
