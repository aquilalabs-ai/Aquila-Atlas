/**
 * SSE streaming helper for the chat endpoint.
 *
 * Uses fetch + ReadableStream instead of EventSource so we can:
 * - Send a POST body
 * - Pass auth headers
 * - Support AbortController cancellation
 */

export interface ChatStreamEvent {
  token?: string
  status?: string
  session_id?: string
  done?: boolean
  input_tokens?: number
  output_tokens?: number
}

export async function* streamChat(
  repoId: string,
  message: string,
  sessionId: string | undefined,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const base = (import.meta.env.VITE_API_URL as string | undefined) ?? ''
  const key  = import.meta.env.VITE_API_KEY  as string | undefined
  const hdrs: Record<string, string> = { 'Content-Type': 'application/json' }
  if (key) hdrs['X-API-Key'] = key

  const res = await fetch(`${base}/repos/${encodeURIComponent(repoId)}/chat`, {
    method: 'POST',
    headers: hdrs,
    body: JSON.stringify({ message, session_id: sessionId, stream: true }),
    signal,
  })

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(text)
  }

  const reader  = res.body.getReader()
  const decoder = new TextDecoder()
  let   buffer  = ''

  // Abort if no data arrives for 90 seconds (LLM hang protection)
  const IDLE_TIMEOUT = 90_000
  let idleTimer: ReturnType<typeof setTimeout> | null = null

  function resetIdle() {
    if (idleTimer) clearTimeout(idleTimer)
    idleTimer = setTimeout(() => {
      reader.cancel()
    }, IDLE_TIMEOUT)
  }

  try {
    resetIdle()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      resetIdle()
      buffer += decoder.decode(value, { stream: true })

      // Split on newlines and process complete SSE lines
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue
        const raw = trimmed.slice(5).trim()
        if (!raw) continue
        try {
          yield JSON.parse(raw) as ChatStreamEvent
        } catch {
          // skip malformed SSE events
        }
      }
    }
  } finally {
    if (idleTimer) clearTimeout(idleTimer)
    reader.releaseLock()
  }
}
