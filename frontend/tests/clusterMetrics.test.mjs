import assert from 'node:assert/strict'
import { aggregateValues, aggregateClusterReports, readClusterReports } from '../src/features/monitoring/clusterMetrics.js'

const nodes = [{id:'a',cpuTotal:8}, {id:'b',cpuTotal:24}]
const sample = (cpu, memory, incoming = 0) => ({cpu_percent:cpu,memory_used_bytes:memory,memory_total_bytes:100,network_in_bytes_per_second:incoming,network_out_bytes_per_second:0})
assert.deepEqual(aggregateValues(nodes,[sample(100,40,10),sample(0,20,20)]),{
  ...sample(25,60,30),memory_total_bytes:200,
})
assert.equal(aggregateValues(nodes,[sample(0,0),sample(0,0)]).cpu_percent,0)
assert.equal(aggregateValues(nodes,[sample(10,0),null]).memory_used_bytes,null)
assert.equal(aggregateValues(nodes,[sample(10,null),sample(0,20)]).memory_used_bytes,null)
assert.equal(aggregateValues([{id:'a',cpuTotal:null}],[sample(10,20)]).cpu_percent,null)
assert.equal(aggregateValues(nodes,[sample(101,0),sample(0,0)]).cpu_percent,null)
assert.equal(aggregateValues([],[]).memory_used_bytes,null)
const report = (node, points, resolution=60) => ({target:{kind:'node',node_id:node},timeframe:'hour',
  current:{available:true,received_at:'2026-09-20T00:00:00Z',values:sample(0,40)},
  history:{available:true,resolution_seconds:resolution,points}})
const ok=value=>({status:'fulfilled',value})
const a=report('a',[{timestamp:60,values:sample(100,20)},{timestamp:120,values:sample(50,30)}])
const b=report('b',[{timestamp:60,values:sample(0,40)},{timestamp:180,values:sample(0,40)}])
const combined=aggregateClusterReports(nodes,[ok(a),ok(b)],'hour',180000)
assert.equal(combined.history.points[0].values.cpu_percent,25,'Unequal nodes must use capacity weights, not arithmetic mean')
assert.equal(combined.history.points[0].values.memory_used_bytes,60)
assert.equal(combined.history.points[1].values.memory_used_bytes,null,'Never interpolate missing node samples into a total')
assert.equal(combined.history.points[2].values.cpu_percent,null)
assert.equal(combined.history.metrics.cpu_percent.missing_points,2)
assert.equal(combined.current.values.cpu_percent,0)
assert.equal(aggregateClusterReports(nodes,[ok(a),{status:'rejected'}],'hour').current.available,false)
assert.equal(aggregateClusterReports(nodes,[ok(a),ok({...b,target:{kind:'node',node_id:'wrong'}})],'hour').observedNodes,1)
assert.equal(aggregateClusterReports(nodes,[ok(a),ok({...b,timeframe:'day'})],'hour').history.points[0].values.cpu_percent,null)
assert.equal(aggregateClusterReports(nodes,[ok(a),ok({...b,history:{...b.history,resolution_seconds:300}})],'hour').history.resolution_seconds,null)
let active=0,peak=0,calls=0
const many=Array.from({length:11},(_,i)=>({id:String(i),cpuTotal:1}))
const results=await readClusterReports(many,'hour',async (_kind,id)=>{
  active++;peak=Math.max(peak,active);calls++
  await new Promise(resolve=>setImmediate(resolve));active--
  if(id==='5') throw new Error('denied')
  return report(id,[])
})
assert.equal(peak,4);assert.equal(calls,11);assert.equal(results[5].status,'rejected')
assert.equal(results[10].value.target.node_id,'10')
let cancelled=true
await readClusterReports(many,'hour',()=>{throw new Error('must not be called')},()=>cancelled)
console.log('cluster weighted totals, null/zero, aligned gaps, target identity, bounded requests and cancellation verified')
