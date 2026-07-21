import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import AdminUsersPage from '../pages/settings/AdminUsersPage'
import CreateVmPage from '../pages/workloads/CreateVmPage'
import DrsPoliciesPage from '../pages/workloads/DrsPoliciesPage'
import NetworkReadinessPage from '../pages/workloads/NetworkReadinessPage'
import RisksPage from '../pages/operations/RisksPage'
import ProxmoxConnectionBoundary from '../shared/proxmox/ProxmoxConnectionBoundary'
import DrsAdvisorPage from '../pages/insights/DrsAdvisorPage'
import InsightsPage from '../pages/insights/InsightsPage'
import JobsPage from '../pages/operations/JobsPage'
import { apiV1Client } from '../shared/api/apiV1'
import { canAdmin, canOperate } from '../shared/auth/permissions'
import { isProxmoxOperational, proxmoxConnectionBadge } from '../shared/proxmox/connection'
import WorkloadCockpitPage from '../pages/workloads/WorkloadCockpitPage'
import OperationsListPage from '../pages/operations/OperationsListPage'
import OperationDetailPage from '../pages/operations/OperationDetailPage'
import GuidedQmUnlockPage from '../pages/operations/GuidedQmUnlockPage'
import Dashboard from '../pages/dashboard/DashboardPage'
import LoginPage from '../pages/auth/LoginPage'
import AccountSettingsScreen from '../pages/settings/AccountSettingsPage'
import AppShell from './AppShell'
import { InsightsShell, OperationsShell, SettingsShell, WorkloadsShell } from './navigation'
import { primaryNavItems } from './navigationModel'

function AdminGuard({ currentUser, children }) {
  return canAdmin(currentUser) ? children : <Navigate to="/" replace />
}

function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [authState, setAuthState] = useState({ status: 'loading', user: null })
  const [proxmoxConnectionState, setProxmoxConnectionState] = useState({ status: 'idle', data: null })

  useEffect(() => {
    let cancelled = false
    async function bootstrapAuth() {
      try {
        const response = await apiV1Client.me()
        if (cancelled) return
        setAuthState(response.authenticated && response.user
          ? { status: 'authenticated', user: response.user }
          : { status: 'anonymous', user: null })
      } catch {
        if (!cancelled) setAuthState({ status: 'anonymous', user: null })
      }
    }
    bootstrapAuth()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (authState.status !== 'authenticated') {
      setProxmoxConnectionState({ status: 'idle', data: null })
      return undefined
    }

    let cancelled = false
    async function loadProxmoxConnection() {
      setProxmoxConnectionState({ status: 'loading', data: null })
      try {
        const data = await apiV1Client.proxmoxConnection()
        if (!cancelled) setProxmoxConnectionState({ status: 'ready', data })
      } catch {
        if (!cancelled) setProxmoxConnectionState({ status: 'error', data: null })
      }
    }
    loadProxmoxConnection()
    return () => {
      cancelled = true
    }
  }, [authState.status])

  const refreshProxmoxConnection = async () => {
    setProxmoxConnectionState({ status: 'loading', data: null })
    try {
      const data = await apiV1Client.proxmoxConnection()
      setProxmoxConnectionState({ status: 'ready', data })
    } catch {
      setProxmoxConnectionState({ status: 'error', data: null })
    }
  }

  const handleLogin = async ({ username, password }) => {
    const response = await apiV1Client.login(username, password)
    setAuthState({ status: 'authenticated', user: response.user })
    return response
  }

  const refreshCurrentUser = async () => {
    try {
      const response = await apiV1Client.me()
      setAuthState(response.authenticated && response.user
        ? { status: 'authenticated', user: response.user }
        : { status: 'anonymous', user: null })
      return response
    } catch {
      setAuthState({ status: 'anonymous', user: null })
      return null
    }
  }

  const handleLogout = async () => {
    try {
      await apiV1Client.logout()
    } finally {
      setAuthState({ status: 'anonymous', user: null })
      setProxmoxConnectionState({ status: 'idle', data: null })
      navigate('/login', { replace: true })
    }
  }

  if (authState.status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 text-sm text-slate-600">
        Loading Gjallar session...
      </div>
    )
  }

  if (authState.status !== 'authenticated') {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage onLogin={handleLogin} />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location }} />} />
      </Routes>
    )
  }

  const currentUser = authState.user
  const proxmoxOperational = proxmoxConnectionState.status === 'ready'
    && isProxmoxOperational(proxmoxConnectionState.data)
  const canMutate = canOperate(currentUser) && proxmoxOperational
  const isAdmin = canAdmin(currentUser)
  const connectionBoundaryProps = {
    requestStatus: proxmoxConnectionState.status,
    connection: proxmoxConnectionState.data,
    onRetry: refreshProxmoxConnection,
  }
  const operationalRoute = (children) => (
    <ProxmoxConnectionBoundary {...connectionBoundaryProps}>{children}</ProxmoxConnectionBoundary>
  )
  const vmInventoryRoute = (
    operationalRoute(
      <WorkloadsShell>
        <WorkloadCockpitPage currentUser={currentUser} canMutate={canMutate} />
      </WorkloadsShell>,
    )
  )
  const drsPoliciesRoute = (
    operationalRoute(
      <WorkloadsShell>
        <DrsPoliciesPage currentUser={currentUser} canManageDrsPolicies={canMutate} />
      </WorkloadsShell>,
    )
  )
  const createVmRoute = (
    operationalRoute(
      <WorkloadsShell>
        <CreateVmPage currentUser={currentUser} canExecuteLiveMutation={canMutate} />
      </WorkloadsShell>,
    )
  )
  const networkReadinessRoute = (
    operationalRoute(
      <WorkloadsShell>
        <NetworkReadinessPage />
      </WorkloadsShell>,
    )
  )
  const jobsRoute = (
    <OperationsShell canExecute={canMutate}>
      <JobsPage />
    </OperationsShell>
  )
  const risksRoute = (
    <OperationsShell canExecute={canMutate}>
      <RisksPage />
    </OperationsShell>
  )
  const insightsRoute = (category = 'overview') => (
    <InsightsShell>
      <InsightsPage category={category} />
    </InsightsShell>
  )
  const operationsRoute = (
    <OperationsShell canExecute={canMutate}>
      <OperationsListPage canExecute={canMutate} />
    </OperationsShell>
  )
  const guidedQmRoute = (
    <OperationsShell canExecute={canMutate}>
      <GuidedQmUnlockPage canExecute={canMutate} />
    </OperationsShell>
  )
  const operationDetailRoute = (
    <OperationsShell canExecute={canMutate}>
      <OperationDetailPage canExecute={canMutate} />
    </OperationsShell>
  )
  const accountRoute = (
    <SettingsShell isAdmin={isAdmin}>
      <AccountSettingsScreen currentUser={currentUser} onPasswordChanged={refreshCurrentUser} />
    </SettingsShell>
  )
  const adminUsersRoute = (
    <SettingsShell isAdmin={isAdmin}>
      <AdminGuard currentUser={currentUser}>
        <AdminUsersPage currentUser={currentUser} onCurrentUserChanged={refreshCurrentUser} />
      </AdminGuard>
    </SettingsShell>
  )
  const connectionBadge = proxmoxConnectionBadge(proxmoxConnectionState.status, proxmoxConnectionState.data)
  const visiblePrimaryNavItems = primaryNavItems.filter((item) => !item.requiresProxmox || proxmoxOperational)

  return (
    <AppShell
      currentUser={currentUser}
      connectionBadge={connectionBadge}
      navItems={visiblePrimaryNavItems}
      pathname={location.pathname}
      onLogout={handleLogout}
    >
      <Routes>
          <Route path="/" element={operationalRoute(<Dashboard />)} />
          <Route path="/instances" element={vmInventoryRoute} />
          <Route path="/instances/drs-policies" element={drsPoliciesRoute} />
          <Route path="/instances/create" element={createVmRoute} />
          <Route path="/instances/networks" element={networkReadinessRoute} />
          <Route
            path="/drs"
            element={operationalRoute(
              <DrsAdvisorPage currentUser={currentUser} canOperate={canMutate} />
            )}
          />
          <Route path="/insights" element={insightsRoute()} />
          <Route path="/insights/risks" element={insightsRoute('risk')} />
          <Route path="/insights/readiness" element={insightsRoute('readiness')} />
          <Route path="/insights/capacity" element={insightsRoute('capacity')} />
          <Route path="/insights/placement" element={insightsRoute('placement')} />
          <Route path="/operations" element={operationsRoute} />
          <Route path="/operations/guided-qm/vm-unlock" element={guidedQmRoute} />
          <Route path="/operations/:operationId" element={operationDetailRoute} />
          <Route path="/operations/jobs" element={jobsRoute} />
          <Route path="/operations/risks" element={risksRoute} />
          <Route path="/settings" element={<Navigate to="/settings/account" replace />} />
          <Route path="/settings/account" element={accountRoute} />
          <Route path="/settings/admin/users" element={adminUsersRoute} />
          <Route path="/infra" element={vmInventoryRoute} />
          <Route path="/create" element={createVmRoute} />
          <Route path="/networks" element={networkReadinessRoute} />
          <Route path="/jobs" element={jobsRoute} />
          <Route path="/risks" element={risksRoute} />
          <Route path="/account" element={accountRoute} />
          <Route path="/admin/users" element={adminUsersRoute} />
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}

export default App
