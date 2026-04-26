/**
 * Hook managing the full test generation lifecycle:
 * idle → submitting → polling → done | error
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, TestContentResponse, TestScope } from '@/lib/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IdleState       { phase: 'idle' }
interface SubmittingState { phase: 'submitting' }
interface PollingState    { phase: 'polling'; jobId: string; completed: number; total: number; currentTarget: string | null; startedAt: number }
interface DoneState       { phase: 'done'; jobId: string; files: Record<string, string>; fileStatuses: Record<string, string> | null; scope: TestScope; languageFilter: string[] | null }
interface ErrorState      { phase: 'error'; message: string }

export type TestGenState = IdleState | SubmittingState | PollingState | DoneState | ErrorState

interface SavedTestJob {
  jobId: string
  repoId: string
  scope: TestScope
  languageFilter: string[] | null
  startedAt: number
}

const STORAGE_KEY = 'aquila-test-job'
const POLL_INTERVAL_MS = 2000
const POLL_MAX_ERRORS = 5

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useTestGeneration(repoId: string) {
  const [jobState, setJobState] = useState<TestGenState>({ phase: 'idle' })
  const [displayOverride, setDisplayOverride] = useState<DoneState | null>(null)
  const state: TestGenState = displayOverride ?? jobState

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollActiveRef = useRef(false)

  function stopPolling() {
    pollActiveRef.current = false
    if (pollRef.current !== null) {
      clearTimeout(pollRef.current)
      pollRef.current = null
    }
  }

  function saveToStorage(job: SavedTestJob) {
    try { localStorage.setItem(STORAGE_KEY + ':' + repoId, JSON.stringify(job)) } catch { /* ignore */ }
  }

  function clearStorage() {
    try { localStorage.removeItem(STORAGE_KEY + ':' + repoId) } catch { /* ignore */ }
  }

  function loadFromStorage(): SavedTestJob | null {
    try {
      const raw = localStorage.getItem(STORAGE_KEY + ':' + repoId)
      return raw ? (JSON.parse(raw) as SavedTestJob) : null
    } catch { return null }
  }

  const startPolling = useCallback((
    jobId: string,
    scope: TestScope,
    languageFilter: string[] | null,
    startedAt = Date.now(),
  ) => {
    stopPolling()
    pollActiveRef.current = true
    let consecutiveErrors = 0

    async function tick() {
      if (!pollActiveRef.current) return
      try {
        const status = await api.getTestJobStatus(repoId, jobId)
        if (!pollActiveRef.current) return
        consecutiveErrors = 0

        if (status.status === 'done') {
          stopPolling()
          const content = await api.getTestContent(repoId, jobId)
          setJobState({ phase: 'done', jobId, files: content.files, fileStatuses: content.file_statuses ?? null, scope, languageFilter })
          clearStorage()
        } else if (status.status === 'failed') {
          stopPolling()
          setJobState({ phase: 'error', message: status.error ?? 'Test generation failed' })
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
          pollRef.current = setTimeout(() => { void tick() }, POLL_INTERVAL_MS * 2)
        }
      }
    }

    void tick()
  }, [repoId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    stopPolling()
    setJobState({ phase: 'idle' })
    setDisplayOverride(null)

    const saved = loadFromStorage()
    if (!saved || saved.repoId !== repoId) return

    let cancelled = false
    api.getTestJobStatus(repoId, saved.jobId).then((status) => {
      if (cancelled) return
      if (status.status === 'done') {
        api.getTestContent(repoId, saved.jobId).then((content) => {
          if (cancelled) return
          setJobState({ phase: 'done', jobId: saved.jobId, files: content.files, fileStatuses: content.file_statuses ?? null, scope: saved.scope, languageFilter: saved.languageFilter })
          clearStorage()
        }).catch(() => clearStorage())
      } else if (status.status === 'running' || status.status === 'queued') {
        setJobState({ phase: 'polling', jobId: saved.jobId, completed: status.completed ?? 0, total: status.total ?? 0, currentTarget: null, startedAt: saved.startedAt })
        startPolling(saved.jobId, saved.scope, saved.languageFilter, saved.startedAt)
      } else {
        clearStorage()
      }
    }).catch((err: unknown) => {
      if (cancelled) return
      const msg = err instanceof Error ? err.message : String(err)
      if (msg.includes('404') || msg.toLowerCase().includes('not found')) {
        clearStorage()
        setJobState({ phase: 'error', message: 'Previous generation job was lost (server may have restarted). Please start a new generation.' })
      } else {
        setJobState({ phase: 'error', message: 'Could not reconnect to generation job: ' + msg })
      }
    })

    return () => { cancelled = true; stopPolling() }
  }, [repoId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function generate(scope: TestScope, languageFilter: string[] | null) {
    setDisplayOverride(null)
    setJobState({ phase: 'submitting' })
    try {
      const resp = await api.generateTests(repoId, {
        scope,
        language_filter: languageFilter ?? undefined,
      })
      const startedAt = Date.now()
      saveToStorage({ jobId: resp.job_id, repoId, scope, languageFilter, startedAt })
      setJobState({ phase: 'polling', jobId: resp.job_id, completed: 0, total: 0, currentTarget: null, startedAt })
      startPolling(resp.job_id, scope, languageFilter, startedAt)
    } catch (err) {
      setJobState({ phase: 'error', message: String(err) })
    }
  }

  function reset() {
    stopPolling()
    clearStorage()
    setJobState({ phase: 'idle' })
    setDisplayOverride(null)
  }

  async function cancel(jobId: string) {
    try { await api.cancelTestJob(repoId, jobId) } catch { /* ignore */ }
  }

  function dismissOverride() {
    setDisplayOverride(null)
  }

  function loadSaved(content: TestContentResponse) {
    setDisplayOverride({
      phase: 'done',
      jobId: content.job_id,
      files: content.files,
      fileStatuses: content.file_statuses ?? null,
      scope: content.scope as TestScope,
      languageFilter: content.language_filter ?? null,
    })
  }

  return { state, generate, reset, cancel, dismissOverride, loadSaved }
}
