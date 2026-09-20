import { useEffect, useRef, useState } from 'react'
import { assertChangeResult } from './changeResult'
import { apiV1Client } from '../../../shared/api/apiV1'

// Resource forms share single-dispatch and canonical Operation verification.
export function useVmChange({ vm, onUpdated, read, mutate, onReview, operationType, operationVmidFromPlan }) {
  const [review, setReview] = useState(null)
  const [plan, setPlan] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const inFlight = useRef(false)
  const generation = useRef(0)
  useEffect(() => () => { generation.current += 1 }, [])

  async function load() {
    if (inFlight.current || submitted) return
    inFlight.current = true
    const current = ++generation.current
    setBusy(true); setError(''); setPlan(null); setReview(null)
    try {
      const data = await read(vm.nodeId, vm.vmid)
      if (generation.current !== current) return
      if (data.target.node_id !== vm.nodeId || Number(data.target.vmid) !== Number(vm.vmid)) throw new Error('조회한 VM이 선택한 대상과 다릅니다.')
      setReview(data)
      onReview(data.observed_before)
    } catch (failure) {
      if (generation.current === current) setError(failure.message)
    } finally {
      if (generation.current === current) { setBusy(false); inFlight.current = false }
    }
  }

  async function execute() {
    if (inFlight.current || submitted || !plan) return
    inFlight.current = true
    const current = ++generation.current
    setSubmitted(true); setBusy(true); setError('')
    try {
      const response = await mutate(vm.nodeId, vm.vmid, plan)
      if (generation.current !== current) return
      setResult({...response, verified: false})
      const observed = await apiV1Client.getOperation(response.operation_id)
      if (generation.current !== current) return
      const operation = assertChangeResult(observed, response.operation_id, operationType ? {
        type: operationType, node: vm.nodeId, vmid: operationVmidFromPlan ? operationVmidFromPlan(plan) : vm.vmid, requested: plan,
      } : null)
      const verified = operation.status === 'succeeded' && !operation.coordination_incomplete && !observed.coordination_incomplete
      const finalResult = {...response, status: operation.status, verified, observed_after: operation.details?.observed_after}
      setResult(finalResult)
      if (verified) onUpdated(finalResult)
    } catch (failure) {
      if (generation.current === current) setError(`${failure.message} 요청 ID를 보존하고 작업 이력을 확인하세요. 자동 재전송하지 않았습니다.`)
    } finally {
      if (generation.current === current) { setBusy(false); inFlight.current = false }
    }
  }

  function resetReview() {
    if (inFlight.current || submitted) return
    generation.current += 1
    setReview(null); setPlan(null); setError('')
  }

  return {review, plan, setPlan, result, error, setError, busy, submitted, load, execute, resetReview}
}
