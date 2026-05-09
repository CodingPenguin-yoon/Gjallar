import { useState, useEffect, useRef } from 'react'
import { Send, Sparkles, Terminal, Play, RotateCcw } from 'lucide-react'
import { llmChat, executeLlmAction, getLlmSessionMessages, clearLlmSession } from '../services/api'

const AUTO_EXECUTED_ACTION_TYPES = new Set([
  'list_vms',
  'list_nodes',
  'get_vm_detail',
  'list_templates',
  'list_storages',
  'list_networks',
])

/**
 * LLM 기반 인프라 채팅 컴포넌트
 *
 * - 자연어 채팅 UI
 * - LLM이 제안한 인프라 액션 목록 표시
 * - 사용자가 액션을 선택/실행 버튼을 눌렀을 때만 실제 인프라 액션 실행
 */
function LlmInfraChat() {
  // 세션 ID를 localStorage에 저장하여 페이지 새로고침 후에도 유지
  const [sessionId, setSessionId] = useState(() => {
    return localStorage.getItem('llm_chat_session_id') || null
  })
  
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content:
        '안녕하세요! Proxmox / Terraform / Ansible 기반 인프라 도우미입니다.\n' +
        '예: "현재 VM 상태 보여줘", "CPU 4코어, 메모리 8GB로 Ubuntu VM 하나 만들어줘"처럼 요청해 보세요.',
    },
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [pendingActions, setPendingActions] = useState([])
  const [selectedActionIndex, setSelectedActionIndex] = useState(null)
  const [isRestoringHistory, setIsRestoringHistory] = useState(false)

  // 채팅 메시지 영역 & 마지막 메시지 DOM 참조
  const messagesContainerRef = useRef(null)
  const messagesEndRef = useRef(null)

  // 페이지 로드 시 세션 이력 복원
  useEffect(() => {
    const restoreSessionHistory = async () => {
      if (!sessionId) return

      setIsRestoringHistory(true)
      try {
        const response = await getLlmSessionMessages(sessionId)
        const data = response.data || response
        const storedMessages = data.messages || []

        if (storedMessages.length > 0) {
          // Redis에 저장된 메시지로 복원
          setMessages(storedMessages)
        }
      } catch (error) {
        console.warn('세션 이력 복원 실패:', error)
        // 복원 실패 시 세션 ID 초기화
        localStorage.removeItem('llm_chat_session_id')
        setSessionId(null)
      } finally {
        setIsRestoringHistory(false)
      }
    }

    restoreSessionHistory()
  }, []) // 컴포넌트 마운트 시 한 번만 실행

  const addMessage = (role, content, extras = {}) => {
    setMessages((prev) => [...prev, { role, content, ...extras }])
  }

  // 새 메시지 추가/복원/로딩 상태 변화 시, 항상 채팅 영역 맨 아래로 스크롤
  useEffect(() => {
    // 1단계: 채팅 패널 내부 스크롤을 맨 아래로 이동
    if (messagesContainerRef.current) {
      const el = messagesContainerRef.current
      el.scrollTop = el.scrollHeight
    }

    // 2단계: 마지막 메시지 요소가 뷰포트 안으로 들어오도록 전체 화면도 따라가게 처리
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'end',
      })
    }
  }, [messages, isLoading, isRestoringHistory])

  const handleSend = async () => {
    const trimmed = input.trim()
    if (!trimmed || isLoading) return

    // 입력 필드를 먼저 비워서 UI에 즉시 반영
    setInput('')
    
    const userMessage = { role: 'user', content: trimmed }
    addMessage('user', trimmed)
    setIsLoading(true)

    try {
      // 세션 ID를 포함하여 LLM API에 전달 (Redis에서 대화 이력 조회)
      const payload = {
        session_id: sessionId, // 세션 ID가 있으면 Redis에서 이력 조회
        messages: sessionId ? [] : messages.map((m) => ({
          // session_id가 있으면 messages는 무시됨 (하위 호환성을 위해 빈 배열이 아닌 전체 전송도 가능)
          role: m.role,
          content: m.content,
        })),
        latest_message: userMessage,
        context: null,
      }

      const response = await llmChat(payload)
      const data = response.data || response

      // 세션 ID 저장 (새로 생성되었거나 기존 것 유지)
      const newSessionId = data.session_id || sessionId
      if (newSessionId && newSessionId !== sessionId) {
        setSessionId(newSessionId)
        localStorage.setItem('llm_chat_session_id', newSessionId)
      }

      const assistantMessage = data.assistant_message || 'LLM 응답을 가져오지 못했습니다.'
      const actions = Array.isArray(data.actions) ? data.actions : []
      const extraData = data.data || null

      // LLM 응답 + 백엔드가 자동 실행한 조회 결과(data)를 함께 메시지에 저장
      addMessage('assistant', assistantMessage, { data: extraData })

      // 읽기 전용(조회) 액션은 이미 백엔드에서 자동 실행되므로
      // 프론트에서는 수동 실행이 필요한 액션만 목록에 표시
      setPendingActions(actions.filter((a) => !AUTO_EXECUTED_ACTION_TYPES.has(a.type)))
      setSelectedActionIndex(null)
    } catch (error) {
      const errorMessage = error.response?.data?.detail || error.message || 'LLM 호출 중 오류가 발생했습니다.'
      addMessage('assistant', `LLM 호출 실패: ${errorMessage}`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleExecuteAction = async (action, index) => {
    if (!action) return
    setSelectedActionIndex(index)
    setIsLoading(true)

    try {
      addMessage(
        'assistant',
        `선택한 액션을 실행합니다:\n- 타입: ${action.type}\n- 설명: ${action.description || '(설명 없음)'}`,
      )

      const response = await executeLlmAction({ action })
      const data = response.data || response

      const resultMessage = data.result_message || '액션 실행 결과 메시지를 가져오지 못했습니다.'
      addMessage('assistant', resultMessage)
    } catch (error) {
      const errorMessage = error.response?.data?.detail || error.message || '액션 실행 중 오류가 발생했습니다.'
      addMessage('assistant', `액션 실행 실패: ${errorMessage}`)
    } finally {
      setIsLoading(false)
      setSelectedActionIndex(null)
    }
  }

  const handleClearSession = async () => {
    if (!sessionId) return

    if (window.confirm('대화 이력을 모두 삭제하시겠습니까?')) {
      try {
        await clearLlmSession(sessionId)
        localStorage.removeItem('llm_chat_session_id')
        setSessionId(null)
        setMessages([
          {
            role: 'assistant',
            content:
              '안녕하세요! Proxmox / Terraform / Ansible 기반 인프라 도우미입니다.\n' +
              '예: "현재 VM 상태 보여줘", "CPU 4코어, 메모리 8GB로 Ubuntu VM 하나 만들어줘"처럼 요청해 보세요.',
          },
        ])
        setPendingActions([])
      } catch (error) {
        console.error('세션 삭제 실패:', error)
      }
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[2fr,1fr] gap-6">
      {/* Chat Panel */}
      <div className="flex flex-col bg-white rounded-lg border border-gray-200 shadow-sm">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-500" />
            <h2 className="text-lg font-semibold text-gray-900">LLM Infra Assistant</h2>
            <span className="ml-2 text-xs px-2 py-0.5 rounded-full bg-purple-50 text-purple-600 border border-purple-100">
              MVP
            </span>
          </div>
          {sessionId && (
            <button
              onClick={handleClearSession}
              className="flex items-center gap-1 px-3 py-1.5 text-xs text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-md transition-colors"
              title="대화 이력 삭제"
            >
              <RotateCcw className="w-3 h-3" />
              초기화
            </button>
          )}
        </div>

        {/* Messages */}
        <div
          ref={messagesContainerRef}
          className="flex-1 px-6 py-4 space-y-4 overflow-y-auto max-h-[520px]"
        >
          {isRestoringHistory && (
            <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
              <Terminal className="w-4 h-4 animate-pulse" />
              <span>이전 대화 이력을 불러오는 중...</span>
            </div>
          )}
          {messages.map((msg, idx) => {
            const isUser = msg.role === 'user'

            // LLM 응답 중 "[자동 실행 결과]" 구분
            let mainText = msg.content || ''
            let autoSection = ''
            if (!isUser && typeof msg.content === 'string') {
              const splitToken = '\n\n[자동 실행 결과]'
              const parts = msg.content.split(splitToken)
              mainText = parts[0]
              if (parts.length > 1) {
                autoSection = '[자동 실행 결과]' + parts.slice(1).join(splitToken)
              }
            }

            const hasVmData = !!msg.data?.vms && Array.isArray(msg.data.vms) && msg.data.vms.length > 0
            const vmNodeFilter = msg.data?.vm_node_filter || null

            const hasNodeData = !!msg.data?.nodes && Array.isArray(msg.data.nodes) && msg.data.nodes.length > 0

            const hasTemplates =
              !!msg.data?.templates && Array.isArray(msg.data.templates) && msg.data.templates.length > 0
            const hasStorages =
              !!msg.data?.storages && Array.isArray(msg.data.storages) && msg.data.storages.length > 0
            const hasNetworks =
              !!msg.data?.networks && Array.isArray(msg.data.networks) && msg.data.networks.length > 0

            return (
              <div key={idx} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm ${
                    isUser
                      ? 'bg-blue-600 text-white rounded-br-sm whitespace-pre-wrap'
                      : 'bg-gray-100 text-gray-900 rounded-bl-sm'
                  }`}
                >
                  {/* 기본 텍스트 응답 */}
                  <div className="whitespace-pre-wrap">{mainText}</div>

                  {/* 백엔드 자동 실행 결과가 있지만 VM 데이터가 없는 경우에는 원문을 그대로 표시 */}
                  {!hasVmData && autoSection && (
                    <div className="mt-3 text-xs text-gray-700 bg-white/60 rounded-md px-3 py-2 whitespace-pre-wrap">
                      {autoSection}
                    </div>
                  )}

                  {/* VM 목록이 있는 경우: 보기 좋은 카드 + View more */}
                  {hasVmData && (
                    <div className="mt-3">
                      <VmListPreview vms={msg.data.vms} nodeFilter={vmNodeFilter} />
                    </div>
                  )}

                  {/* Proxmox 노드 목록 (VM 리스트 카드와 비슷한 표 스타일) */}
                  {hasNodeData && (
                    <div className="mt-3">
                      <NodeListPreview nodes={msg.data.nodes} />
                    </div>
                  )}

                  {/* VM 생성 질의응답용 옵션 리스트들 (템플릿 / 스토리지 / 네트워크) */}
                  {hasTemplates && (
                    <div className="mt-3">
                      <TemplateListPreview templates={msg.data.templates} />
                    </div>
                  )}
                  {hasStorages && (
                    <div className="mt-3">
                      <StorageListPreview storages={msg.data.storages} />
                    </div>
                  )}
                  {hasNetworks && (
                    <div className="mt-3">
                      <NetworkListPreview networks={msg.data.networks} />
                    </div>
                  )}
                </div>
              </div>
            )
          })}
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Terminal className="w-4 h-4 animate-pulse" />
              <span>모델이 응답을 생성 중입니다...</span>
            </div>
          )}
          {/* 스크롤 기준이 되는 마지막 앵커 요소 */}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
          <div className="flex items-end gap-3">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                // 한글/일본어 등 IME 조합 입력 중에는 Enter를 눌러도 전송하지 않도록 방지
                // (e.nativeEvent.isComposing 이 true 이면 아직 글자가 확정되지 않은 상태)
                if (e.key === 'Enter' && !e.shiftKey) {
                  if (e.nativeEvent.isComposing) {
                    return
                  }
                  e.preventDefault()
                  e.stopPropagation()
                  handleSend()
                }
              }}
              placeholder='예: "현재 VM들 상태 요약해줘", "CPU 4코어 8GB Ubuntu VM 하나 생성해줘"'
              rows={2}
              className="flex-1 resize-none rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !input.trim()}
              className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium shadow-sm hover:bg-blue-700 disabled:bg-gray-300 disabled:text-gray-500 disabled:cursor-not-allowed"
            >
              <Send className="w-4 h-4" />
              보내기
            </button>
          </div>
        </div>
      </div>

      {/* Actions Panel */}
      <div className="flex flex-col bg-white rounded-lg border border-gray-200 shadow-sm">
        <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-200">
          <Play className="w-4 h-4 text-green-500" />
          <h3 className="text-sm font-semibold text-gray-900">제안된 인프라 액션</h3>
        </div>

        <div className="flex-1 px-6 py-4 space-y-3 overflow-y-auto max-h-[520px]">
          {pendingActions.length === 0 && (
            <p className="text-sm text-gray-500">
              아직 실행 가능한 액션이 없습니다.
              <br />
              VM 조회나 생성에 대한 요청을 보내면 여기에서 제안된 액션이 표시됩니다.
            </p>
          )}

          {pendingActions.map((action, index) => (
            <div
              key={index}
              className={`border rounded-lg p-3 text-sm space-y-2 ${
                selectedActionIndex === index ? 'border-blue-500 bg-blue-50' : 'border-gray-200 bg-gray-50'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <div>
                  <div className="text-xs font-semibold uppercase text-gray-500">Action Type</div>
                  <div className="text-sm font-medium text-gray-900">{action.type}</div>
                </div>
                <button
                  onClick={() => handleExecuteAction(action, index)}
                  disabled={isLoading}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-green-600 text-white text-xs font-medium hover:bg-green-700 disabled:bg-gray-300 disabled:text-gray-500 disabled:cursor-not-allowed"
                >
                  <Play className="w-3 h-3" />
                  실행
                </button>
              </div>

              {action.description && (
                <p className="text-xs text-gray-700 border-t border-dashed border-gray-200 pt-2">
                  {action.description}
                </p>
              )}

              {action.params && Object.keys(action.params).length > 0 && (
                <div className="text-xs text-gray-600 bg-white border border-gray-200 rounded-md px-2 py-1">
                  <div className="font-semibold mb-1">매개변수</div>
                  <dl className="space-y-0.5">
                    {Object.entries(action.params).map(([key, value]) => (
                      <div key={key} className="flex justify-between gap-2">
                        <dt className="text-gray-500">{key}</dt>
                        <dd className="text-gray-800 text-right break-all">
                          {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default LlmInfraChat

// ---------------------------------------------------------------------------
// VM / 노드 목록 프리뷰 컴포넌트
// - VM: 전체 노드 기준으로 정렬 후 최대 30개까지만 표시 (+ 더 보기 토글)
// - 특정 노드 조회(list_vms with node): 해당 노드의 VM만 필터링해서 전부 표시
// - 노드: VM 카드와 비슷한 스타일의 테이블로 표시
// ---------------------------------------------------------------------------

function VmListPreview({ vms, nodeFilter }) {
  const [showAll, setShowAll] = useState(false)

  // 특정 노드 필터가 있는 경우, 해당 노드의 VM만 사용
  const normalizedFilter = nodeFilter ? nodeFilter.toString().toLowerCase() : null
  const baseVms =
    normalizedFilter
      ? vms.filter((vm) => (vm.node || '').toString().toLowerCase() === normalizedFilter)
      : vms

  const total = baseVms.length

  // 일반 "VM 목록" 요청 시에는 최대 30개까지만 표시 (너무 길어지는 것 방지)
  // 특정 노드 필터가 있을 때는 전체를 다 보여준다.
  const MAX_DISPLAY = 30

  // 상태/노드/이름 기준으로 정렬
  const sortedVms = [...baseVms].sort((a, b) => {
    const aStatus = (a.status || '').toString().toLowerCase()
    const bStatus = (b.status || '').toString().toLowerCase()

    const aRunning = aStatus === 'running'
    const bRunning = bStatus === 'running'

    // 1순위: running 먼저
    if (aRunning !== bRunning) {
      return aRunning ? -1 : 1
    }

    // 2순위: 노드 이름
    const aNode = (a.node || '').toString()
    const bNode = (b.node || '').toString()
    if (aNode !== bNode) {
      return aNode.localeCompare(bNode, 'ko-KR')
    }

    // 3순위: VM 이름
    const aName = (a.name || a.vm_id || a.id || '').toString()
    const bName = (b.name || b.vm_id || b.id || '').toString()
    return aName.localeCompare(bName, 'ko-KR')
  })

  const displayVms = normalizedFilter
    ? sortedVms
    : sortedVms.slice(0, showAll ? total : MAX_DISPLAY)

  // 노드 기준으로 그룹핑
  const nodeMap = displayVms.reduce((acc, vm) => {
    const nodeName = vm.node || '노드 미지정'
    if (!acc[nodeName]) {
      acc[nodeName] = []
    }
    acc[nodeName].push(vm)
    return acc
  }, {})

  const nodeNames = Object.keys(nodeMap).sort((a, b) => a.localeCompare(b, 'ko-KR'))

  return (
    <div className="bg-white/70 border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 space-y-2">
      <div className="font-semibold text-gray-900 flex items-center justify-between">
        <span>Proxmox VM 목록 요약</span>
        <span className="text-[11px] text-gray-500">
          {total}개 VM
          {!normalizedFilter && total > MAX_DISPLAY && !showAll && ` (최대 ${MAX_DISPLAY}개까지만 표시)`}
        </span>
      </div>

      {/* 노드별 박스로 묶어서 표시 */}
      <div className="space-y-3">
        {nodeNames.map((nodeName) => {
          const nodeVms = nodeMap[nodeName]
          return (
            <div
              key={nodeName}
              className="border border-gray-200 rounded-md bg-white/80 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
            >
              <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-gray-100 bg-gray-50/80">
                <div className="text-[11px] font-semibold text-gray-800">
                  노드: <span className="text-gray-900">{nodeName}</span>
                </div>
                <div className="text-[11px] text-gray-500">{nodeVms.length}개 VM</div>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full text-[11px] border-collapse">
                  <thead>
                    <tr className="border-b border-gray-100 bg-white">
                      <th className="py-1.5 pr-3 text-left font-semibold text-gray-700 text-[11px]">VM 이름</th>
                      <th className="py-1.5 px-3 text-left font-semibold text-gray-700 text-[11px] whitespace-nowrap">
                        상태
                      </th>
                      <th className="py-1.5 px-3 text-left font-semibold text-gray-700 text-[11px] whitespace-nowrap">
                        리소스
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {nodeVms.map((vm, idx) => (
                      <tr
                        key={vm.vmid || vm.id || `${nodeName}-${idx}`}
                        className="border-t border-gray-100 hover:bg-gray-50/70"
                      >
                        <td className="py-1.5 pr-3 align-middle">
                          <div className="font-medium text-[13px] text-gray-900">
                            {vm.name || vm.vm_id || vm.id || '이름 없음'}
                            {vm.vmid && <span className="ml-1 text-[11px] text-gray-500">#{vm.vmid}</span>}
                          </div>
                        </td>
                        <td className="py-1.5 px-3 align-middle whitespace-nowrap">
                          <StatusPill status={vm.status} />
                        </td>
                        <td className="py-1.5 px-3 align-middle whitespace-nowrap text-gray-700">
                          {/* CPU / 메모리 / 디스크 요약 */}
                          {(() => {
                            const cpu = vm.cpu_cores ?? vm.cpu ?? '-'
                            const mem = vm.memory_gb ?? vm.memory ?? '-'

                            // ProxmoxService 에서 계산한 총 디스크 용량(disk_gb) 우선 사용
                            let diskTotal = vm.disk_gb
                            // 없으면 disks 배열에서 합산
                            if ((diskTotal == null || Number.isNaN(diskTotal)) && Array.isArray(vm.disks)) {
                              diskTotal = vm.disks.reduce((sum, d) => {
                                const size = typeof d.size_gb === 'number' ? d.size_gb : 0
                                return sum + size
                              }, 0)
                            }

                            const diskCount = Array.isArray(vm.disks) ? vm.disks.length : 0
                            const diskText =
                              diskTotal && diskTotal > 0
                                ? ` · 디스크 ${Math.round(diskTotal)}GB${diskCount > 1 ? ` (${diskCount}개)` : ''}`
                                : ''

                            return (
                              <>
                                CPU {cpu} · 메모리 {mem}GB
                                {diskText}
                              </>
                            )
                          })()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })}
      </div>

      {!normalizedFilter && total > MAX_DISPLAY && (
        <button
          type="button"
          onClick={() => setShowAll((prev) => !prev)}
          className="mt-1 inline-flex items-center text-[11px] font-medium text-blue-600 hover:text-blue-700"
        >
          {showAll ? `처음 ${MAX_DISPLAY}개만 보기` : `나머지 ${total - MAX_DISPLAY}개 더 보기`}
        </button>
      )}
    </div>
  )
}

function NodeListPreview({ nodes }) {
  const items = Array.isArray(nodes) ? nodes : []
  if (items.length === 0) return null

  // 이름 기준 정렬
  const sorted = [...items].sort((a, b) => {
    const aName = (a.name || a.server_name || a.id || '').toString()
    const bName = (b.name || b.server_name || b.id || '').toString()
    return aName.localeCompare(bName, 'ko-KR')
  })

  return (
    <div className="bg-white/70 border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 space-y-2">
      <div className="font-semibold text-gray-900 flex items-center justify-between">
        <span>Proxmox 노드 목록</span>
        <span className="text-[11px] text-gray-500">{sorted.length}개 노드</span>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-[11px] border-collapse">
          <thead>
            <tr className="border-b border-gray-100 bg-white">
              <th className="py-1.5 pr-3 text-left font-semibold text-gray-700 text-[11px]">노드 이름</th>
              <th className="py-1.5 px-3 text-left font-semibold text-gray-700 text-[11px] whitespace-nowrap">
                상태
              </th>
              <th className="py-1.5 px-3 text-left font-semibold text-gray-700 text-[11px] whitespace-nowrap">
                리소스
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((n, idx) => {
              const name = n.name || n.server_name || n.id || '이름 없음'
              const status = n.status || 'unknown'
              // backend에서는 memory 가 바이트 단위 maxmem 이라 가정하고 GB로 변환 시도
              let memGb = null
              if (typeof n.memory === 'number' && n.memory > 0) {
                memGb = Math.round(n.memory / 1024 / 1024 / 1024)
              }
              const cpu = n.cpu ?? 0

              return (
                <tr key={n.id || name || idx} className="border-t border-gray-100 hover:bg-gray-50/70">
                  <td className="py-1.5 pr-3 align-middle">
                    <div className="font-medium text-[12px] text-gray-900">{name}</div>
                  </td>
                  <td className="py-1.5 px-3 align-middle whitespace-nowrap">
                    <StatusPill status={status} />
                  </td>
                  <td className="py-1.5 px-3 align-middle whitespace-nowrap text-gray-700">
                    CPU {cpu} · 메모리 {memGb != null ? `${memGb}GB` : '-'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function StatusPill({ status }) {
  const normalized = (status || '').toString().toLowerCase()
  const isRunning = normalized === 'running'
  const isStopped = normalized === 'stopped'

  let colorClass = 'bg-gray-100 text-gray-700 border-gray-200'
  let label = status || 'unknown'

  if (isRunning) {
    colorClass = 'bg-green-100 text-green-800 border-green-200'
  } else if (isStopped) {
    colorClass = 'bg-gray-100 text-gray-800 border-gray-300'
  }

  return (
    <span className={`px-1.5 py-0.5 rounded-full border text-[11px] font-semibold ${colorClass}`}>
      {label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// VM 생성 질의응답용 옵션 리스트 프리뷰 컴포넌트들
// - 템플릿 / 스토리지 / 네트워크 후보를 간단히 표 형태로 보여줌
// ---------------------------------------------------------------------------

function TemplateListPreview({ templates }) {
  const items = Array.isArray(templates) ? templates : []
  if (items.length === 0) return null

  // 노드 기준으로 그룹핑
  const nodeMap = items.reduce((acc, t) => {
    const nodeName = (t.node || '노드 미지정').toString()
    if (!acc[nodeName]) {
      acc[nodeName] = []
    }
    acc[nodeName].push(t)
    return acc
  }, {})

  const nodeNames = Object.keys(nodeMap).sort((a, b) => a.localeCompare(b, 'ko-KR'))

  return (
    <div className="bg-white/70 border border-purple-200 rounded-lg px-3 py-2 text-xs text-gray-800 space-y-2">
      <div className="font-semibold text-gray-900 flex items-center justify-between">
        <span>VM 템플릿 목록</span>
        <span className="text-[11px] text-gray-500">{items.length}개 템플릿</span>
      </div>

      {/* 노드별 박스로 묶어서 표시 (VM 목록 카드와 유사한 구조) */}
      <div className="space-y-3">
        {nodeNames.map((nodeName) => {
          const nodeTemplates = nodeMap[nodeName]
          return (
            <div
              key={nodeName}
              className="border border-purple-100 rounded-md bg-white/80 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
            >
              <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-purple-50 bg-purple-50/60">
                <div className="text-[11px] font-semibold text-gray-800">
                  노드: <span className="text-gray-900">{nodeName}</span>
                </div>
                <div className="text-[11px] text-gray-500">{nodeTemplates.length}개 템플릿</div>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full text-[11px] border-collapse">
                  <thead>
                    <tr className="border-b border-gray-100 bg-white">
                      <th className="py-1.5 pr-3 text-left font-semibold text-gray-700 text-[11px]">템플릿 이름</th>
                      <th className="py-1.5 px-3 text-left font-semibold text-gray-700 text-[11px] whitespace-nowrap">
                        ID
                      </th>
                      <th className="py-1.5 px-3 text-left font-semibold text-gray-700 text-[11px] whitespace-nowrap">
                        리소스
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {nodeTemplates.map((t, idx) => {
                      const mem = t.memory_gb != null ? Math.round(t.memory_gb) : null
                      return (
                        <tr
                          key={t.template_id || t.id || `${nodeName}-${idx}`}
                          className="border-t border-gray-100 hover:bg-gray-50/70"
                        >
                          <td className="py-1.5 pr-3 align-middle">
                            <div className="font-medium text-[12px] text-gray-900">
                              {t.template_name || t.name || '이름 없음'}
                              {t.vmid && <span className="ml-1 text-[11px] text-gray-500">#{t.vmid}</span>}
                            </div>
                          </td>
                          <td className="py-1.5 px-3 align-middle whitespace-nowrap text-gray-700">
                            {t.template_id || t.id || '-'}
                          </td>
                          <td className="py-1.5 px-3 align-middle whitespace-nowrap text-gray-700">
                            CPU {t.cpu_cores ?? '-'} · 메모리 {mem != null ? `${mem}GB` : '-'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })}
      </div>

      <p className="text-[11px] text-gray-500">
        위 목록에서 원하는 템플릿의 <span className="font-semibold">template_id</span>를 골라서 말씀해 주세요.
      </p>
    </div>
  )
}

function StorageListPreview({ storages }) {
  const items = Array.isArray(storages) ? storages : []
  if (items.length === 0) return null

  return (
    <div className="bg-white/70 border border-emerald-200 rounded-lg px-3 py-2 text-xs text-gray-800 space-y-2">
      <div className="font-semibold text-gray-900 flex items-center justify-between">
        <span>스토리지 목록</span>
        <span className="text-[11px] text-gray-500">{items.length}개 스토리지</span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-[11px] border-collapse">
          <thead>
            <tr className="border-b border-gray-100 bg-white">
              <th className="py-1.5 pr-3 text-left font-semibold text-gray-700 text-[11px]">이름</th>
              <th className="py-1.5 px-3 text-left font-semibold text-gray-700 text-[11px] whitespace-nowrap">
                ID
              </th>
              <th className="py-1.5 px-3 text-left font-semibold text-gray-700 text-[11px] whitespace-nowrap">
                타입 / 용량
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((s, idx) => (
              <tr key={s.storage_id || s.id || idx} className="border-t border-gray-100 hover:bg-gray-50/70">
                <td className="py-1.5 pr-3 align-middle">
                  <div className="font-medium text-[12px] text-gray-900">{s.storage_name || s.name || '이름 없음'}</div>
                </td>
                <td className="py-1.5 px-3 align-middle whitespace-nowrap text-gray-700">
                  {s.storage_id || s.id || '-'}
                </td>
                <td className="py-1.5 px-3 align-middle whitespace-nowrap text-gray-700">
                  {s.type || 'unknown'}
                  {s.size_gb != null && (
                    <>
                      {' '}
                      · {s.size_gb}GB
                      {s.available_gb != null && <> (가용 {s.available_gb}GB)</>}
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-gray-500">
        위 목록에서 사용할 <span className="font-semibold">storage_id</span> 또는 이름을 골라서 말씀해 주세요.
      </p>
    </div>
  )
}

function NetworkListPreview({ networks }) {
  const items = Array.isArray(networks) ? networks : []
  if (items.length === 0) return null

  return (
    <div className="bg-white/70 border border-sky-200 rounded-lg px-3 py-2 text-xs text-gray-800 space-y-2">
      <div className="font-semibold text-gray-900 flex items-center justify-between">
        <span>네트워크(브리지) 목록</span>
        <span className="text-[11px] text-gray-500">{items.length}개 네트워크</span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-[11px] border-collapse">
          <thead>
            <tr className="border-b border-gray-100 bg-white">
              <th className="py-1.5 pr-3 text-left font-semibold text-gray-700 text-[11px]">이름</th>
              <th className="py-1.5 px-3 text-left font-semibold text-gray-700 text-[11px] whitespace-nowrap">
                ID
              </th>
              <th className="py-1.5 px-3 text-left font-semibold text-gray-700 text-[11px] whitespace-nowrap">
                타입 / 정보
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((n, idx) => (
              <tr key={n.network_id || n.id || idx} className="border-t border-gray-100 hover:bg-gray-50/70">
                <td className="py-1.5 pr-3 align-middle">
                  <div className="font-medium text-[12px] text-gray-900">{n.network_name || n.name || '이름 없음'}</div>
                </td>
                <td className="py-1.5 px-3 align-middle whitespace-nowrap text-gray-700">
                  {n.network_id || n.id || '-'}
                </td>
                <td className="py-1.5 px-3 align-middle whitespace-nowrap text-gray-700">
                  {n.type || 'bridge'}
                  {n.cidr && <> · {n.cidr}</>}
                  {n.gateway && <> · GW {n.gateway}</>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-gray-500">
        위 목록에서 사용할 <span className="font-semibold">network_ids</span>(브리지 이름)을 한 개 이상 골라서 말씀해 주세요.
      </p>
    </div>
  )
}
