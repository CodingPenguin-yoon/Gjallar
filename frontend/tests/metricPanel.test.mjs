import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { transformSync } from 'esbuild'
import vm from 'node:vm'
import * as React from 'react'
import * as runtime from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import * as model from '../src/features/monitoring/model.js'
const module = {exports:{}}
const source = readFileSync(new URL('../src/features/monitoring/MetricPanel.jsx', import.meta.url),'utf8')
const compiled = transformSync(source,{loader:'jsx',format:'cjs',jsx:'automatic'}).code
new vm.Script(`(function(require,module,exports){${compiled}})`).runInThisContext()(name => {
  if(name==='react')return React
  if(name==='react/jsx-runtime')return runtime
  if(name==='./model')return model
  throw new Error(name)
},module,module.exports)
const metric={key:'cpu_percent',label:'CPU',unit:'%'}
const history={available:true,points:[{timestamp:60,values:{cpu_percent:25}},{timestamp:120,values:{cpu_percent:null}}],metrics:{cpu_percent:{observed_points:1,missing_points:1,latest_value_at:60,stale:true}},start:60,end:120,resolution_seconds:60}
const render=props=>renderToStaticMarkup(React.createElement(module.exports.default,{metric,history,...props}))
const zero=render({current:{available:true,received_at:'2026-09-20T00:00:00Z',values:{cpu_percent:0}}})
assert.match(zero,/>0\.0%</)
assert.match(zero,/현재 조회/)
assert.doesNotMatch(zero,/최신 여부 주의/)
const missing=render({current:{available:true,values:{cpu_percent:null}}})
assert.match(missing,/마지막 이력/)
assert.match(missing,/최신 여부 주의/)
assert.match(missing,/>25\.0%</)
assert.match(missing,/누락 1/)
const unavailable=render({history:{available:false,message:'권한 부족'},current:{available:false}})
assert.match(unavailable,/관찰 없음/)
assert.match(unavailable,/권한 부족/)
assert.doesNotMatch(unavailable,/<svg/)
assert.match(render({inspect:true}),/CPU 시각 선택/)
console.log('metric panels distinguish zero, missing current, stale history and unavailable charts')
const memory = render({metric:{key:'memory_used_bytes',label:'메모리 사용',unit:'bytes'},history:{available:true,points:[{timestamp:60,values:{memory_used_bytes:1024,memory_total_bytes:4096}}],metrics:{},start:60,end:60,resolution_seconds:60},current:{available:true,received_at:'2026-09-20T00:00:00Z',values:{memory_used_bytes:1024,memory_total_bytes:4096}}})
assert.match(memory,/4\.0 KiB/, 'Memory graph scale should include known capacity, not make a small usage appear full')
