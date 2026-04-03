import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { SessionInfo } from '@/lib/api'

export interface SourceLocation {
  repoId: string
  filePath: string
  line?: number
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

interface AppState {
  // Theme
  theme: 'dark' | 'light'
  toggleTheme: () => void

  // Active repository
  activeRepoId: string | null
  setActiveRepoId: (id: string | null) => void

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
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
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
    }),
    {
      name: 'aquila-atlas-ui-v3',
      partialize: (s) => ({
        theme:          s.theme,
        activeRepoId:   s.activeRepoId,
        activeSessions: s.activeSessions,
        chatMessages:   s.chatMessages,
        sessions:       s.sessions,
      }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          document.documentElement.classList.toggle('dark', state.theme === 'dark')
        }
      },
    },
  ),
)
