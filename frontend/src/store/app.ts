import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { SessionInfo, AuthUser } from '@/lib/api'
import { api } from '@/lib/api'

export type { AuthUser }

export interface SourceLocation {
  repoId: string
  filePath: string
  line?: number
  endLine?: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  status?: string
  isStreaming?: boolean
  inputTokens?: number
  outputTokens?: number
}

export interface RepoSource {
  path: string
  source_type: 'local' | 'github' | 'gitlab' | 'gitea' | 'git'
  github_token?: string
  has_token?: boolean  // true when a token was provided at ingest time (used to prompt on resync)
}

interface AppState {
  // Auth
  authToken: string | null
  authRefreshToken: string | null
  authUser: AuthUser | null
  authDisabled: boolean   // true when backend has AUTH_MODE=disabled
  authChecked: boolean    // true once the startup /auth/me check has completed
  setAuth: (token: string, refreshToken: string, user: AuthUser) => void
  clearAuth: () => void
  setAuthDisabled: () => void
  setAuthChecked: () => void

  // Theme
  theme: 'dark' | 'light'
  toggleTheme: () => void

  // Active repository
  activeRepoId: string | null
  setActiveRepoId: (id: string | null) => void

  // Stored source info per repo (populated on connect, used for resync)
  repoSources: Record<string, RepoSource>
  setRepoSource: (repoId: string, source: RepoSource) => void
  clearRepoSource: (repoId: string) => void

  // Active session per repo  (repoId → sessionId)
  activeSessions: Record<string, string>
  setActiveSession: (repoId: string, sessionId: string) => void
  clearActiveSession: (repoId: string) => void

  // Chat messages keyed by sessionId
  chatMessages: Record<string, ChatMessage[]>
  setChatMessages: (sessionId: string, msgs: ChatMessage[]) => void
  appendChatMessage: (sessionId: string, msg: ChatMessage) => void
  updateChatMessage: (sessionId: string, msgId: string, update: Partial<ChatMessage>) => void
  clearChatMessages: (sessionId: string) => void

  // Persisted session metadata — survives server restarts
  sessions: Record<string, SessionInfo>
  upsertSession: (session: SessionInfo) => void
  removeSessions: (sessionIds: string[]) => void

  // Source file viewer
  sourceLocation: SourceLocation | null
  openSource: (loc: SourceLocation) => void
  closeSource: () => void

  // File index cache (repoId → sorted file paths) — not persisted
  fileIndex: Record<string, string[]>
  loadFileIndex: (repoId: string) => Promise<void>
}

// Tracks in-flight loadFileIndex calls so concurrent renders don't fan out to the server.
const _fileIndexLoading = new Set<string>()

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      // ── Auth ──────────────────────────────────────────────────────────
      authToken: null,
      authRefreshToken: null,
      authUser: null,
      authDisabled: false,
      authChecked: false,
      setAuth: (token, refreshToken, user) =>
        set({ authToken: token, authRefreshToken: refreshToken, authUser: user, authChecked: true }),
      clearAuth: () =>
        set({
          authToken: null,
          authRefreshToken: null,
          authUser: null,
          authChecked: true,
          // Clear all repo-scoped state so a new user session starts clean.
          activeRepoId: null,
          activeSessions: {},
          chatMessages: {},
          sessions: {},
          repoSources: {},
          sourceLocation: null,
        }),
      setAuthDisabled: () =>
        set({ authDisabled: true, authChecked: true }),
      setAuthChecked: () =>
        set({ authChecked: true }),

      // ── Theme ─────────────────────────────────────────────────────────
      theme: 'dark',
      toggleTheme: () =>
        set((s) => {
          const next = s.theme === 'dark' ? 'light' : 'dark'
          document.documentElement.classList.toggle('dark', next === 'dark')
          return { theme: next }
        }),

      // ── Active repo ────────────────────────────────────────────────────
      activeRepoId: null,
      setActiveRepoId: (id) => set({ activeRepoId: id, sourceLocation: null }),

      // ── Repo sources ───────────────────────────────────────────────────
      repoSources: {},
      setRepoSource: (repoId, source) =>
        set((s) => ({ repoSources: { ...s.repoSources, [repoId]: source } })),
      clearRepoSource: (repoId) =>
        set((s) => {
          const next = { ...s.repoSources }
          delete next[repoId]
          return { repoSources: next }
        }),

      // ── Active sessions ────────────────────────────────────────────────
      activeSessions: {},
      setActiveSession: (repoId, sessionId) =>
        set((s) => ({ activeSessions: { ...s.activeSessions, [repoId]: sessionId } })),
      clearActiveSession: (repoId) =>
        set((s) => {
          const next = { ...s.activeSessions }
          delete next[repoId]
          return { activeSessions: next }
        }),

      // ── Chat messages (keyed by sessionId) ───────────────────────────
      chatMessages: {},
      setChatMessages: (sessionId, msgs) =>
        set((s) => ({ chatMessages: { ...s.chatMessages, [sessionId]: msgs } })),
      appendChatMessage: (sessionId, msg) =>
        set((s) => ({
          chatMessages: {
            ...s.chatMessages,
            [sessionId]: [...(s.chatMessages[sessionId] ?? []), msg],
          },
        })),
      updateChatMessage: (sessionId, msgId, update) =>
        set((s) => ({
          chatMessages: {
            ...s.chatMessages,
            [sessionId]: (s.chatMessages[sessionId] ?? []).map((m) =>
              m.id === msgId ? { ...m, ...update } : m,
            ),
          },
        })),
      clearChatMessages: (sessionId) =>
        set((s) => {
          const next = { ...s.chatMessages }
          delete next[sessionId]
          return { chatMessages: next }
        }),

      // ── Persisted sessions ────────────────────────────────────────────
      sessions: {},
      upsertSession: (session) =>
        set((s) => ({ sessions: { ...s.sessions, [session.session_id]: session } })),
      removeSessions: (ids) =>
        set((s) => {
          const next = { ...s.sessions }
          ids.forEach((id) => delete next[id])
          return { sessions: next }
        }),

      // ── Source viewer ─────────────────────────────────────────────────
      sourceLocation: null,
      openSource: (loc) => set({ sourceLocation: loc }),
      closeSource: () => set({ sourceLocation: null }),

      // ── File index cache ──────────────────────────────────────────────
      fileIndex: {},
      loadFileIndex: async (repoId) => {
        // Key-presence check (not truthiness) so an empty [] result counts as cached.
        if (repoId in useAppStore.getState().fileIndex) return
        if (_fileIndexLoading.has(repoId)) return
        _fileIndexLoading.add(repoId)
        try {
          const res = await api.listFiles(repoId)
          set((s) => ({ fileIndex: { ...s.fileIndex, [repoId]: res.files } }))
        } catch {
          // Leave absent — next render will retry rather than caching a failure.
        } finally {
          _fileIndexLoading.delete(repoId)
        }
      },
    }),
    {
      name: 'aquila-atlas-ui-v3',
      partialize: (s) => ({
        theme:             s.theme,
        activeRepoId:      s.activeRepoId,
        activeSessions:    s.activeSessions,
        chatMessages:      s.chatMessages,
        sessions:          s.sessions,
        repoSources:       s.repoSources,
        authToken:         s.authToken,
        authRefreshToken:  s.authRefreshToken,
        authUser:          s.authUser,
      }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          document.documentElement.classList.toggle('dark', state.theme === 'dark')
          // Clear any messages that were left in a streaming state from a previous session
          for (const sid of Object.keys(state.chatMessages)) {
            state.chatMessages[sid] = state.chatMessages[sid].map((m) =>
              m.isStreaming ? { ...m, isStreaming: false, status: undefined } : m,
            )
          }
        }
      },
    },
  ),
)
