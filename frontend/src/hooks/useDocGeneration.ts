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
interface PollingState    { phase: 'polling'; jobId: string; completed: number; total: number; currentTarget: string | null }
interface DoneState       { phase: 'done'; jobId: string; files: Record<string, string>; scope: DocScope; style: DocStyle; language: DocLanguage }
interface ErrorState      { phase: 'error'; message: string }

export type DocGenState = IdleState | SubmittingState | PollingState | DoneState | ErrorState

interface SavedDocJob {
  jobId: string
  repoId: string
  scope: DocScope
  style: DocStyle
  language: DocLanguage
}

const STORAGE_KEY = 'aquila-doc-job'
const POLL_INTERVAL_MS = 2000

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

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  function stopPolling() {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
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

  const startPolling = useCallback((jobId: string, scope: DocScope, style: DocStyle, language: DocLanguage) => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const status = await api.getDocJobStatus(repoId, jobId)
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
          })
        }
      } catch (err) {
        stopPolling()
        setJobState({ phase: 'error', message: String(err) })
        clearStorage()
      }
    }, POLL_INTERVAL_MS)
  }, [repoId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Restore from localStorage on mount
  // ------------------------------------------------------------------

  useEffect(() => {
    const saved = loadFromStorage()
    if (!saved || saved.repoId !== repoId) return
    api.getDocJobStatus(repoId, saved.jobId).then((status) => {
      if (status.status === 'done') {
        api.getDocContent(repoId, saved.jobId).then((content) => {
          setJobState({ phase: 'done', jobId: saved.jobId, files: content.files, scope: saved.scope, style: saved.style, language: saved.language })
          clearStorage()
        }).catch(() => clearStorage())
      } else if (status.status === 'running' || status.status === 'queued') {
        setJobState({ phase: 'polling', jobId: saved.jobId, completed: status.completed ?? 0, total: status.total ?? 0, currentTarget: null })
        startPolling(saved.jobId, saved.scope, saved.style, saved.language)
      } else {
        clearStorage()
      }
    }).catch(() => clearStorage())

    return () => stopPolling()
  }, [repoId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Public actions
  // ------------------------------------------------------------------

  async function generate(scope: DocScope, style: DocStyle, language: DocLanguage) {
    setDisplayOverride(null)
    setJobState({ phase: 'submitting' })
    try {
      const resp = await api.generateDocs(repoId, { scope, style, language })
      saveToStorage({ jobId: resp.job_id, repoId, scope, style, language })
      setJobState({ phase: 'polling', jobId: resp.job_id, completed: 0, total: 0, currentTarget: null })
      startPolling(resp.job_id, scope, style, language)
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

  return { state, generate, reset, dismissOverride, loadSaved }
}
