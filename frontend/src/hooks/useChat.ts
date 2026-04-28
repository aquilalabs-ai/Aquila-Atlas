import { useCallback, useRef, useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { streamChat } from '@/lib/sse'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/app'
import type { ChatMessage } from '@/store/app'
import type { SessionInfo } from '@/lib/api'

export type { ChatMessage as Message } from '@/store/app'

export function useChat(repoId: string) {
  const qc = useQueryClient()

  const activeSessionId  = useAppStore((s) => s.activeSessions[repoId])
  const setActiveSession = useAppStore((s) => s.setActiveSession)

  const appendMessage  = useAppStore((s) => s.appendChatMessage)
  const updateMessage  = useAppStore((s) => s.updateChatMessage)
  const upsertSession  = useAppStore((s) => s.upsertSession)

  // Messages are keyed by sessionId; fall back to empty array
  const messages = useAppStore((s) =>
    activeSessionId ? (s.chatMessages[activeSessionId] ?? []) : [],
  )

  const setChatMessages = useAppStore((s) => s.setChatMessages)

  const abortCtlRef  = useRef<AbortController | null>(null)
  const isLoadingRef = useRef(false)
  const [historyLoading, setHistoryLoading] = useState(false)

  const lastMsg   = messages[messages.length - 1]
  const isLoading = (lastMsg?.role === 'assistant' && lastMsg?.isStreaming === true) || historyLoading

  // When the repo changes, release the loading lock for the new context.
  // Do NOT abort the old stream — let it complete in the background so its
  // message is preserved in the store and visible when the user switches back.
  useEffect(() => {
    isLoadingRef.current = false
  }, [repoId])

  // When switching to a session that has server-side history but no local cache
  // (e.g. after a logout/login), fetch the history from the server.
  useEffect(() => {
    if (!activeSessionId) return
    const localMessages = useAppStore.getState().chatMessages[activeSessionId]
    if (localMessages && localMessages.length > 0) return
    const sessionInfo = useAppStore.getState().sessions[activeSessionId]
    if (!sessionInfo || sessionInfo.message_count === 0) return

    setHistoryLoading(true)
    api.getSessionMessages(repoId, activeSessionId)
      .then((msgs) => {
        if (msgs.length === 0) return
        const hydrated: ChatMessage[] = msgs.map((m) => ({
          id:   crypto.randomUUID(),
          role: m.role,
          content: m.content,
        }))
        setChatMessages(activeSessionId, hydrated)
      })
      .catch(() => { /* best-effort — silently ignore if history unavailable */ })
      .finally(() => setHistoryLoading(false))
  }, [activeSessionId, repoId, setChatMessages])

  const send = useCallback(
    async (content: string) => {
      if (!content.trim() || isLoadingRef.current) return
      isLoadingRef.current = true

      // Ensure a server session exists before sending
      let sid = activeSessionId
      if (!sid) {
        try {
          const created = await api.createSession(repoId)
          sid = created.session_id
          const info: SessionInfo = {
            session_id:    sid,
            repo_id:       repoId,
            title:         content.trim().slice(0, 60),
            created_at:    created.created_at,
            message_count: 0,
          }
          upsertSession(info)
          setActiveSession(repoId, sid)
          void qc.invalidateQueries({ queryKey: ['sessions', repoId] })
        } catch {
          isLoadingRef.current = false
          return
        }
      }

      const userMsg: ChatMessage = {
        id:   crypto.randomUUID(),
        role: 'user',
        content,
      }
      const assistantId = crypto.randomUUID()
      const placeholder: ChatMessage = {
        id:          assistantId,
        role:        'assistant',
        content:     '',
        status:      'Starting response...',
        isStreaming: true,
      }

      appendMessage(sid, userMsg)
      appendMessage(sid, placeholder)

      const ctl = new AbortController()
      abortCtlRef.current = ctl

      let finalInputTokens = 0
      let finalOutputTokens = 0

      try {
        for await (const event of streamChat(repoId, content, sid, ctl.signal)) {
          if (ctl.signal.aborted) break

          if (event.done) {
            // Server echoes back the session_id on done — keep in sync
            if (event.session_id && event.session_id !== sid) {
              setActiveSession(repoId, event.session_id)
            }
            // Store final token counts
            if (event.input_tokens !== undefined) finalInputTokens = event.input_tokens
            if (event.output_tokens !== undefined) finalOutputTokens = event.output_tokens
            // Refresh session list so title / message_count stay up-to-date
            void qc.invalidateQueries({ queryKey: ['sessions', repoId] })
            break
          }

          if (event.status) {
            updateMessage(sid, assistantId, { status: event.status })
            continue
          }

          if (event.token) {
            const current  = useAppStore.getState().chatMessages[sid]
            const existing = current?.find((m) => m.id === assistantId)
            updateMessage(sid, assistantId, {
              content: (existing?.content ?? '') + event.token,
              status:  undefined,
            })
          }
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') return
        const msg = err instanceof Error ? err.message : 'Unknown error'
        updateMessage(sid, assistantId, { content: `_Stream error: ${msg}_` })
      } finally {
        updateMessage(sid, assistantId, { 
          isStreaming: false,
          inputTokens: finalInputTokens,
          outputTokens: finalOutputTokens,
        })
        isLoadingRef.current = false
        abortCtlRef.current  = null
      }
    },
    [repoId, activeSessionId, appendMessage, updateMessage, setActiveSession, qc],
  )

  const regenerate = useCallback(async () => {
    if (!activeSessionId || isLoadingRef.current) return
    const current = useAppStore.getState().chatMessages[activeSessionId] ?? []
    // Find the last user message preceding the last assistant message
    const lastUserMsg = [...current].reverse().find((m) => m.role === 'user')
    if (!lastUserMsg) return
    // Drop the last assistant message so we get a fresh one
    const withoutLast = current[current.length - 1]?.role === 'assistant'
      ? current.slice(0, -1)
      : current
    useAppStore.getState().setChatMessages(activeSessionId, withoutLast)
    await send(lastUserMsg.content)
  }, [activeSessionId, send])

  return { messages, isLoading, error: null as string | null, send, regenerate }
}
