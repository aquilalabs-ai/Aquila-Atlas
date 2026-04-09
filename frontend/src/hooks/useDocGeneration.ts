/**
 * Hook managing the full documentation generation lifecycle:
 * idle → submitting → polling → done | error
 *
 * Two separate pieces of state:
 *   jobState       — tracks the active generation job (updated by the poll interval)
 *   displayOverride — set when the user opens a saved doc while a job is running;
 *                     the poll keeps going in the background so progress isn't lost.
 *
 * The component always sees `displayOverride ?? jobState`.
 *
 * Back-button behaviour:
 *   • from a saved doc   → dismissOverride()  (clears override, shows job state)
 *   • from a generated doc → reset()          (stops poll, returns to idle)
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, DocContentResponse, DocLanguage, DocScope, DocStyle } from '@/lib/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IdleState       { phase: 'idle' }
interface SubmittingState { phase: 'submitting' }
interface PollingState    { phase: 'polling'; jobId: string; completed: number; total: number; currentTarget: string | null; startedAt: number }
interface DoneState       { phase: 'done'; jobId: string; files: Record<string, string>; scope: DocScope; style: DocStyle; language: DocLanguage }
interface ErrorState      { phase: 'error'; message: string }

export type DocGenState = IdleState | SubmittingState | PollingState | DoneState | ErrorState

interface SavedDocJob {
  jobId: string
  repoId: string
  scope: DocScope
  style: DocStyle
  language: DocLanguage
  startedAt: number
}

const STORAGE_KEY = 'aquila-doc-job'
const POLL_INTERVAL_MS = 2000
const POLL_MAX_ERRORS = 5  // consecutive failures before giving up

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useDocGeneration(repoId: string) {
  // Tracks the active generation job (idle when nothing is running).
  const [jobState, setJobState] = useState<DocGenState>({ phase: 'idle' })

  // Non-null when the user explicitly opened a saved doc.
  // This is what the component renders; the poll keeps updating jobState behind the scenes.
  const [displayOverride, setDisplayOverride] = useState<DoneState | null>(null)

  // What the component sees
  const state: DocGenState = displayOverride ?? jobState

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollActiveRef = useRef(false)

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  function stopPolling() {
    pollActiveRef.current = false
    if (pollRef.current !== null) {
      clearTimeout(pollRef.current)
      pollRef.current = null
    }
  }

  function saveToStorage(job: SavedDocJob) {
    try { localStorage.setItem(STORAGE_KEY + ':' + repoId, JSON.stringify(job)) } catch { /* ignore */ }
  }

  function clearStorage() {
    try { localStorage.removeItem(STORAGE_KEY + ':' + repoId) } catch { /* ignore */ }
  }

  function loadFromStorage(): SavedDocJob | null {
    try {
      const raw = localStorage.getItem(STORAGE_KEY + ':' + repoId)
      return raw ? (JSON.parse(raw) as SavedDocJob) : null
    } catch { return null }
  }

  // ------------------------------------------------------------------
  // Poll a job until done / failed — updates jobState only
  // ------------------------------------------------------------------

  const startPolling = useCallback((jobId: string, scope: DocScope, style: DocStyle, language: DocLanguage, startedAt = Date.now()) => {
    stopPolling()
    pollActiveRef.current = true
    let consecutiveErrors = 0

    async function tick() {
      if (!pollActiveRef.current) return
      try {
        const status = await api.getDocJobStatus(repoId, jobId)
        if (!pollActiveRef.current) return
        consecutiveErrors = 0

        if (status.status === 'done') {
          stopPolling()
          const content = await api.getDocContent(repoId, jobId)
          setJobState({ phase: 'done', jobId, files: content.files, scope, style, language })
          clearStorage()
        } else if (status.status === 'failed') {
          stopPolling()
          setJobState({ phase: 'error', message: status.error ?? 'Documentation generation failed' })
          clearStorage()
        } else {
          setJobState({
            phase: 'polling',
            jobId,
            completed: status.completed ?? 0,
            total: status.total ?? 0,
            currentTarget: status.current_target ?? null,
            startedAt,
          })
          if (pollActiveRef.current) {
            pollRef.current = setTimeout(() => { void tick() }, POLL_INTERVAL_MS)
          }
        }
      } catch (err) {
        if (!pollActiveRef.current) return
        consecutiveErrors++
        if (consecutiveErrors >= POLL_MAX_ERRORS) {
          stopPolling()
          setJobState({ phase: 'error', message: String(err) })
          clearStorage()
        } else {
          // Transient error — retry after a longer delay
          pollRef.current = setTimeout(() => { void tick() }, POLL_INTERVAL_MS * 2)
        }
      }
    }

    void tick()
  }, [repoId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Restore from localStorage on mount
  // ------------------------------------------------------------------

  useEffect(() => {
    // Reset to idle immediately when repo changes — each repo has independent state.
    // The async restore below will quickly move back to polling/done if a job exists.
    stopPolling()
    setJobState({ phase: 'idle' })
    setDisplayOverride(null)

    const saved = loadFromStorage()
    if (!saved || saved.repoId !== repoId) return

    let cancelled = false
    api.getDocJobStatus(repoId, saved.jobId).then((status) => {
      if (cancelled) return
      if (status.status === 'done') {
        api.getDocContent(repoId, saved.jobId).then((content) => {
          if (cancelled) return
          setJobState({ phase: 'done', jobId: saved.jobId, files: content.files, scope: saved.scope, style: saved.style, language: saved.language })
          clearStorage()
        }).catch(() => clearStorage())
      } else if (status.status === 'running' || status.status === 'queued') {
        setJobState({ phase: 'polling', jobId: saved.jobId, completed: status.completed ?? 0, total: status.total ?? 0, currentTarget: null, startedAt: saved.startedAt })
        startPolling(saved.jobId, saved.scope, saved.style, saved.language, saved.startedAt)
      } else {
        clearStorage()
      }
    }).catch((err: unknown) => {
      if (cancelled) return
      const msg = err instanceof Error ? err.message : String(err)
      // 404 = server lost the job (restart / eviction); surface it rather than silently resetting
      if (msg.includes('404') || msg.toLowerCase().includes('not found')) {
        clearStorage()
        setJobState({ phase: 'error', message: 'Previous generation job was lost (server may have restarted). Please start a new generation.' })
      } else {
        // Transient network error — keep localStorage so next reload can retry
        setJobState({ phase: 'error', message: 'Could not reconnect to generation job: ' + msg })
      }
    })

    return () => { cancelled = true; stopPolling() }
  }, [repoId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Public actions
  // ------------------------------------------------------------------

  async function generate(scope: DocScope, style: DocStyle, language: DocLanguage, excludeExtensions?: string[]) {
    setDisplayOverride(null)
    setJobState({ phase: 'submitting' })
    try {
      const resp = await api.generateDocs(repoId, { scope, style, language, exclude_extensions: excludeExtensions })
      const startedAt = Date.now()
      saveToStorage({ jobId: resp.job_id, repoId, scope, style, language, startedAt })
      setJobState({ phase: 'polling', jobId: resp.job_id, completed: 0, total: 0, currentTarget: null, startedAt })
      startPolling(resp.job_id, scope, style, language, startedAt)
    } catch (err) {
      setJobState({ phase: 'error', message: String(err) })
    }
  }

  /** Full reset — stops any active poll and returns to idle. */
  function reset() {
    stopPolling()
    clearStorage()
    setJobState({ phase: 'idle' })
    setDisplayOverride(null)
  }

  /** Cancel the active generation job on the server.
   *  The backend saves partial files and marks the job done — keep polling
   *  so the UI naturally transitions to the done state with whatever was completed.
   */
  async function cancel(jobId: string) {
    try {
      await api.cancelDocJob(repoId, jobId)
    } catch { /* ignore — job may have already finished */ }
    // Poll keeps running; the next tick will see status=done and load partial files
  }

  /**
   * Dismiss a saved-doc override and reveal the current job state.
   * The poll (if any) was never interrupted, so progress is intact.
   */
  function dismissOverride() {
    setDisplayOverride(null)
  }

  /** Show a saved doc without interrupting any active generation job. */
  function loadSaved(content: DocContentResponse) {
    setDisplayOverride({
      phase: 'done',
      jobId: content.job_id,
      files: content.files,
      scope: content.scope as DocScope,
      style: content.style as DocStyle,
      language: content.language as DocLanguage,
    })
  }

  return { state, generate, reset, cancel, dismissOverride, loadSaved }
}
