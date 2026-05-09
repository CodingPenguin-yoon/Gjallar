import { apiV1Client } from '../services/apiV1.js'
import { buildInfraExplorerModel } from './apiV1ViewModels.js'

function pickList(payload, key) {
  if (Array.isArray(payload)) return payload
  if (payload && Array.isArray(payload[key])) return payload[key]
  if (payload && Array.isArray(payload.items)) return payload.items
  return []
}

export async function loadInfraExplorerModel(client = apiV1Client) {
  const [nodesPayload, vmsPayload] = await Promise.all([
    client.listNodes(),
    client.listVms(),
  ])

  return buildInfraExplorerModel({
    nodes: pickList(nodesPayload, 'nodes'),
    vms: pickList(vmsPayload, 'vms'),
  })
}
