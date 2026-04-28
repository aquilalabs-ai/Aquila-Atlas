import { useEffect } from 'react'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/app'

/**
 * Runs once on app startup. Calls GET /auth/me to determine auth state:
 *   200  → token valid, user set in store
 *   401  → auth enabled but no valid token → show login
 *   501  → AUTH_MODE=disabled on backend → skip login entirely
 */
export function useAuth() {
  const authChecked      = useAppStore((s) => s.authChecked)
  const authDisabled     = useAppStore((s) => s.authDisabled)
  const authUser         = useAppStore((s) => s.authUser)
  const setAuth          = useAppStore((s) => s.setAuth)
  const clearAuth        = useAppStore((s) => s.clearAuth)
  const setAuthDisabled  = useAppStore((s) => s.setAuthDisabled)

  useEffect(() => {
    if (authChecked) return
    api.authCheck().then(({ status, user }) => {
      // A login or activate may have completed while this check was in-flight.
      // If authChecked is already true, another action owns the auth state — don't override it.
      const live = useAppStore.getState()
      if (live.authChecked) return

      if (status === 501) {
        setAuthDisabled()
      } else if (status === 200 && user) {
        setAuth(live.authToken ?? '', live.authRefreshToken ?? '', user)
      } else {
        clearAuth()
      }
    }).catch(() => {
      if (!useAppStore.getState().authChecked) clearAuth()
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const isAuthenticated = authDisabled || authUser !== null

  return { authChecked, authDisabled, authUser, isAuthenticated }
}
