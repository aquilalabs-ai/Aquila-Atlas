import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { SessionInfo } from '@/lib/api'
import { useAppStore } from '@/store/app'

export function useSessionList(repoId: string) {
  const upsertSession  = useAppStore((s) => s.upsertSession)
  const removeSessions = useAppStore((s) => s.removeSessions)

  const query = useQuery({
    queryKey: ['sessions', repoId],
    queryFn: () => api.listSessions(repoId),
    enabled: Boolean(repoId),
    refetchInterval: false,
    staleTime: 10_000,
  })

  // Merge server sessions into local store and prune any stale local sessions
  // that no longer exist on the server (e.g. expired / deleted from the DB).
  useEffect(() => {
    if (!query.data) return

    query.data.sessions.forEach((s) => upsertSession(s))

    // Remove sessions for this repo that the server no longer knows about.
    const serverIds = new Set(query.data.sessions.map((s) => s.session_id))
    const staleIds = Object.values(useAppStore.getState().sessions)
      .filter((s) => s.repo_id === repoId && !serverIds.has(s.session_id))
      .map((s) => s.session_id)
    if (staleIds.length > 0) removeSessions(staleIds)
  }, [query.data, repoId, upsertSession, removeSessions])

  return query
}

export function useCreateSession(repoId: string) {
  const qc            = useQueryClient()
  const setActive     = useAppStore((s) => s.setActiveSession)
  const upsertSession = useAppStore((s) => s.upsertSession)

  return useMutation({
    mutationFn: (title: string = 'New Chat') => api.createSession(repoId, title),
    onSuccess: (data) => {
      const info: SessionInfo = {
        session_id:    data.session_id,
        repo_id:       data.repo_id,
        title:         data.title,
        created_at:    data.created_at,
        message_count: 0,
      }
      upsertSession(info)
      setActive(repoId, data.session_id)
      void qc.invalidateQueries({ queryKey: ['sessions', repoId] })
    },
  })
}

export function useDeleteSession(repoId: string) {
  const qc             = useQueryClient()
  const activeSessions = useAppStore((s) => s.activeSessions)
  const clearActive    = useAppStore((s) => s.clearActiveSession)
  const setActive      = useAppStore((s) => s.setActiveSession)
  const clearMessages  = useAppStore((s) => s.clearChatMessages)
  const removeSessions = useAppStore((s) => s.removeSessions)

  return useMutation({
    mutationFn: (sessionId: string) => api.deleteSession(repoId, sessionId),
    onSuccess: (_data, sessionId) => {
      clearMessages(sessionId)
      removeSessions([sessionId])

      if (activeSessions[repoId] === sessionId) {
        clearActive(repoId)
      }

      void qc.invalidateQueries({ queryKey: ['sessions', repoId] }).then(() => {
        const cached = qc.getQueryData<Awaited<ReturnType<typeof api.listSessions>>>(['sessions', repoId])
        const first  = cached?.sessions[0]
        if (first) setActive(repoId, first.session_id)
      })
    },
  })
}
