import VmTemplatePanel from './VmTemplatePanel'
import VmConsolePanel from './VmConsolePanel'
import VmDeletePanel from './VmDeletePanel'
import VmComputePanel from './VmComputePanel'
import VmClonePanel from './VmClonePanel'
import VmNetworkPanel from './VmNetworkPanel'
import VmDiskPanel from './VmDiskPanel'

function ResourceGroup({ title, children }) {
  return <details className="gj-disclosure">
    <summary>{title}</summary><div>{children}</div>
  </details>
}

export default function VmResourcePanels(props) {
  return <>
    <VmConsolePanel {...props} />
    <div className="mt-5 space-y-3">
      <p className="text-sm text-slate-600">아래 설정 변경은 VM을 정상 종료한 뒤 진행합니다. 작업을 펼쳐 입력과 영향을 확인하세요.</p>
      <ResourceGroup title="CPU·메모리 변경"><VmComputePanel {...props} /></ResourceGroup>
      <ResourceGroup title="디스크 확장"><VmDiskPanel {...props} /></ResourceGroup>
      <ResourceGroup title="네트워크 변경"><VmNetworkPanel {...props} /></ResourceGroup>
      <ResourceGroup title="VM 복제"><VmClonePanel {...props} /></ResourceGroup>
      <ResourceGroup title="템플릿 전환"><VmTemplatePanel {...props} /></ResourceGroup>
      <details className="rounded-lg border border-red-200 px-4 py-3">
        <summary className="cursor-pointer font-semibold text-red-800">VM 영구 삭제 · 되돌릴 수 없음</summary>
        <VmDeletePanel {...props} />
      </details>
    </div>
  </>
}
