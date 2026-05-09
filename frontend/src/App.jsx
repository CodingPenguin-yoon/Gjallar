import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { AlertTriangle, Clock3, LayoutDashboard, List, Plus, Server } from 'lucide-react'
import CreateInstanceWizard from './components/CreateInstanceWizard'
import InstanceList from './components/InstanceList'
import OperationalRiskDashboard from './components/OperationalRiskDashboard'
import TaskBoard from './components/TaskBoard'

const navItems = [
  { label: 'Dashboard', path: '/', icon: LayoutDashboard, end: true },
  { label: 'Infra Explorer', path: '/infra', icon: List },
  { label: 'Create VM', path: '/create', icon: Plus },
  { label: 'Jobs/Runs', path: '/jobs', icon: Clock3 },
  { label: 'Risks/Alerts', path: '/risks', icon: AlertTriangle },
]

const dashboardCards = [
  {
    label: 'Infra Explorer',
    path: '/infra',
    description: '노드와 VM 상태를 /api/v1 기준으로 읽기 전용 조회합니다.',
  },
  {
    label: 'Create VM',
    path: '/create',
    description: 'draft, preflight, plan, approve까지만 연결된 안전한 요청 흐름입니다.',
  },
  {
    label: 'Jobs/Runs',
    path: '/jobs',
    description: '작업 실행 이력과 산출물을 읽기 전용으로 추적합니다.',
  },
  {
    label: 'Risks/Alerts',
    path: '/risks',
    description: '운영 위험 신호를 수정 없이 검토합니다.',
  },
]

function navClass({ isActive }) {
  return `flex shrink-0 items-center gap-2 px-6 py-4 font-medium transition-colors border-b-2 ${
    isActive
      ? 'text-slate-900 border-slate-900 bg-slate-50'
      : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-50'
  }`
}

function Dashboard() {
  const navigate = useNavigate()

  return (
    <section className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">Gjallar PRD v1 MVP</p>
        <h2 className="mt-3 text-3xl font-semibold text-slate-950">Dashboard</h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
          현재 콘솔은 PRD 기준 화면만 노출합니다. 인프라 조회, VM 생성 요청 검토, 작업 이력, 위험 신호를
          /api/v1 경계 안에서 다루며 live 실행 버튼은 제공하지 않습니다.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {dashboardCards.map((card) => (
          <button
            key={card.path}
            type="button"
            onClick={() => navigate(card.path)}
            className="rounded-xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:border-slate-400 hover:shadow"
          >
            <div className="text-lg font-semibold text-slate-950">{card.label}</div>
            <p className="mt-2 text-sm leading-6 text-slate-600">{card.description}</p>
          </button>
        ))}
      </div>
    </section>
  )
}

function App() {
  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="container mx-auto px-8 py-5">
          <div className="flex items-center gap-3">
            <Server className="w-8 h-8 text-slate-700" />
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">Gjallar Operations Console</h1>
              <p className="text-sm text-gray-500">PRD v1 MVP · /api/v1 only</p>
            </div>
          </div>
        </div>
      </header>

      <nav className="bg-white border-b border-gray-200 shadow-sm" aria-label="Gjallar primary navigation">
        <div className="container mx-auto px-8">
          <div className="flex overflow-x-auto">
            {navItems.map(({ label, path, icon: Icon, end }) => (
              <NavLink key={path} to={path} end={end} className={navClass}>
                <Icon className="w-5 h-5" />
                {label}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      <main className="container mx-auto px-8 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route
            path="/infra"
            element={
              <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
                <InstanceList />
              </div>
            }
          />
          <Route
            path="/create"
            element={
              <div className="max-w-5xl mx-auto rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
                <CreateInstanceWizard />
              </div>
            }
          />
          <Route path="/jobs" element={<TaskBoard />} />
          <Route
            path="/risks"
            element={
              <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
                <OperationalRiskDashboard />
              </div>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
