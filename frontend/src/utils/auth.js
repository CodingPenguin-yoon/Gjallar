export const ROLE_ORDER = Object.freeze({
  viewer: 10,
  operator: 20,
  admin: 30,
})

export function normalizeRole(role) {
  return String(role || '').trim().toLowerCase()
}

export function hasRole(user, requiredRole) {
  const actual = ROLE_ORDER[normalizeRole(user?.role)]
  const required = ROLE_ORDER[normalizeRole(requiredRole)]
  return Number.isFinite(actual) && Number.isFinite(required) && actual >= required
}

export function canOperate(user) {
  return hasRole(user, 'operator')
}

export function authFailureMessage(error, fallback = '요청을 처리하지 못했습니다.') {
  if (error?.status === 401) return '로그인이 필요합니다.'
  if (error?.status === 403) return '권한이 부족합니다.'
  return error?.message || fallback
}
