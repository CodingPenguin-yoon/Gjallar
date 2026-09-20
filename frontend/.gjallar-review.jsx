import React from 'react'
import {createRoot} from 'react-dom/client'
import {MemoryRouter} from 'react-router-dom'
import './src/index.css'
const observedAt = new Date().toISOString()
const source = {available:true, complete:true, expected_targets:1, observed_targets:1, failed_targets:[]}
window.fetch = async (url, options={}) => {
  if (options.method && options.method !== 'GET') throw new Error('Read-only navigation fixture')
  const path = String(url).split('?')[0]
  let data, meta = {}
  if (path === '/api/v1/auth/me') data={authenticated:true,user:{username:'검토용 관리자',user_id:'fixture-admin',role:'admin'}}
  else if (path === '/api/v1/setup/proxmox/connection') data={state:'live',source:'live_read_only',inventory_available:true,configured:true,freshness:'fresh',observed_at:observedAt}
  else if (path === '/api/v1/vms/40000') {
    data={vmid:40000,name:'검토용 정지 VM',node_id:'node1',status:'stopped',template:false,cpu:2,memory_mb:2048,disk_gb:20,storage_id:'nas-server',disks:[{device:'scsi0',size_gb:20,storage_id:'nas-server'}],allowed_actions:['start']}
    meta={source:'live_read_only',observed_at:observedAt,freshness:'fresh',availability:{available:true,complete:true,sources:{vm_config:source,vm_detail:source,guest_agent:source}}}
  } else if (path === '/api/v1/operations') data={operations:[]}
  else if (path === '/api/v1/setup/proxmox/registrations') data={attempts:[]}
  else if (path === '/api/v1/insights') data={generated_at:observedAt,status:'ready',sections:Object.fromEntries(['risks','readiness','capacity','placement'].map(category=>[category,{available:true,freshness:'fresh',status:'ready',source:'fixture',observed_at:observedAt,findings:[],summary:{finding_count:0}}]))}
  else throw new Error('Unimplemented read-only navigation fixture: '+path)
  return new Response(JSON.stringify({ok:true,data,meta}),{status:200,headers:{'content-type':'application/json'}})
}
const {default:App}=await import('./src/app/App.jsx')
createRoot(document.getElementById('root')).render(<MemoryRouter initialEntries={['/instances/templates/cleanup?node=node1&vmid=40000&build=fixture-image-build&resource=template']}><App/></MemoryRouter>)
