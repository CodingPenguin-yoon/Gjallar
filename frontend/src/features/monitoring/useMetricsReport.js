import { useEffect, useState } from 'react'
import { apiV1Client } from '../../shared/api/apiV1'
import { metricsTargetMatches } from './model'

export default function useMetricsReport(kind, node, resource, timeframe, refreshKey = 0) {
  const [state, setState] = useState({ report: null, busy: false, error: '' })
  const identity = JSON.stringify([kind, node, resource, timeframe, refreshKey])
  useEffect(() => {
    if (!node || (kind !== 'node' && !resource)) return
    let cancelled = false
    setState({ identity, report: null, busy: true, error: '' })
    apiV1Client.getMetrics(kind, node, resource, timeframe).then(report => {
      if (!metricsTargetMatches(report, kind, node, resource, timeframe)) throw new Error('조회된 지표 대상 또는 기간이 선택과 다릅니다.')
      if (!cancelled) setState({ identity, report, busy: false, error: '' })
    }).catch(error => {
      if (!cancelled) setState({ identity, report: null, busy: false, error: error.message })
    })
    return () => { cancelled = true }
  }, [identity, kind, node, resource, timeframe, refreshKey])
  return state.identity === identity ? state : { report: null, busy: Boolean(node), error: '' }
}
