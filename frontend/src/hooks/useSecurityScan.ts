/**
 * Hook managing the security scan lifecycle:
 * idle → submitting → polling → done | error
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, SecurityFinding, SecurityReport, SecurityScanRequest } from '@/lib/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IdleState       { phase: 'idle' }
interface SubmittingState { phase: 'submitting' }
interface PollingState    {
  phase: 'polling'
  jobId: string
  source: string
  completed: number
  total: number
  currentPhase: string | null
  startedAt: number
  severityCounts: Record<string, number>
}
interface DoneState {
  phase: 'done'
  jobId: string
  source: string
  findings: SecurityFinding[]
  report: string
  severityCounts: Record<string, number>
  toolsUsed: string[]
}
interface ErrorState { phase: 'error'; message: string }

export type SecurityScanState = IdleState | SubmittingState | PollingState | DoneState | ErrorState

interface SavedScanJob {
  jobId: string
  repoId: string
  source: string
  startedAt: number
}

const STORAGE_KEY = 'aquila-security-scan'
const POLL_INTERVAL_MS = 2000
const POLL_MAX_ERRORS = 5

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useSecurityScan(repoId: string) {
  const [jobState, setJobState] = useState<SecurityScanState>({ phase: 'idle' })
  const [displayOverride, setDisplayOverride] = useState<DoneState | null>(null)
  const state: SecurityScanState = displayOverride ?? jobState

  const pollRef  = useRef<ReturnType<typeof setTimeout> | null>(null)
  const activeRef = useRef(false)

  function stopPolling() {
    activeRef.current = false
    if (pollRef.current !== null) {
      clearTimeout(pollRef.current)
      pollRef.current = null
    }
  }

  function saveToStorage(job: SavedScanJob) {
    try { localStorage.setItem(`${STORAGE_KEY}:${repoId}`, JSON.stringify(job)) } catch { /* ignore */ }
  }

  function clearStorage() {
    try { localStorage.removeItem(`${STORAGE_KEY}:${repoId}`) } catch { /* ignore */ }
  }

  function loadFromStorage(): SavedScanJob | null {
    try {
      const raw = localStorage.getItem(`${STORAGE_KEY}:${repoId}`)
      return raw ? (JSON.parse(raw) as SavedScanJob) : null
    } catch { return null }
  }

  const startPolling = useCallback((
    jobId: string,
    source: string,
    startedAt = Date.now(),
  ) => {
    stopPolling()
    activeRef.current = true
    let consecutiveErrors = 0

    async function tick() {
      if (!activeRef.current) return
      try {
        const status = await api.getSecurityJobStatus(repoId, jobId)
        if (!activeRef.current) return
        consecutiveErrors = 0

        if (status.status === 'done') {
          stopPolling()
          const report = await api.getSecurityScan(repoId, jobId)
          setJobState({
            phase: 'done',
            jobId,
            source,
            findings: report.findings,
            report: report.report,
            severityCounts: report.severity_counts,
            toolsUsed: report.tools_used ?? [],
          })
          clearStorage()
        } else if (status.status === 'failed') {
          stopPolling()
          setJobState({ phase: 'error', message: status.error ?? 'Security scan failed' })
          clearStorage()
        } else {
          setJobState({
            phase: 'polling',
            jobId,
            source,
            completed: status.completed ?? 0,
            total: status.total ?? 4,
            currentPhase: status.current_phase ?? null,
            startedAt,
            severityCounts: status.severity_counts ?? {},
          })
          if (activeRef.current) {
            pollRef.current = setTimeout(() => { void tick() }, POLL_INTERVAL_MS)
          }
        }
      } catch (err) {
        if (!activeRef.current) return
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

  // Restore in-flight scan on mount
  useEffect(() => {
    stopPolling()
    setJobState({ phase: 'idle' })
    setDisplayOverride(null)

    const saved = loadFromStorage()
    if (!saved || saved.repoId !== repoId) return

    let cancelled = false
    api.getSecurityJobStatus(repoId, saved.jobId).then((status) => {
      if (cancelled) return
      if (status.status === 'done') {
        api.getSecurityScan(repoId, saved.jobId).then((report) => {
          if (cancelled) return
          setJobState({
            phase: 'done',
            jobId: saved.jobId,
            source: saved.source,
            findings: report.findings,
            report: report.report,
            severityCounts: report.severity_counts,
            toolsUsed: report.tools_used ?? [],
          })
          clearStorage()
        }).catch(() => clearStorage())
      } else if (status.status === 'running' || status.status === 'queued') {
        setJobState({
          phase: 'polling',
          jobId: saved.jobId,
          source: saved.source,
          completed: status.completed ?? 0,
          total: status.total ?? 4,
          currentPhase: null,
          startedAt: saved.startedAt,
          severityCounts: {},
        })
        startPolling(saved.jobId, saved.source, saved.startedAt)
      } else {
        clearStorage()
      }
    }).catch((err: unknown) => {
      if (cancelled) return
      const msg = err instanceof Error ? err.message : String(err)
      if (msg.includes('404') || msg.toLowerCase().includes('not found')) {
        clearStorage()
      } else {
        setJobState({ phase: 'error', message: 'Could not reconnect to scan job: ' + msg })
      }
    })

    return () => { cancelled = true; stopPolling() }
  }, [repoId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function scan(req: SecurityScanRequest) {
    setDisplayOverride(null)
    setJobState({ phase: 'submitting' })
    try {
      const resp = await api.submitSecurityScan(repoId, req)
      const startedAt = Date.now()
      saveToStorage({ jobId: resp.job_id, repoId, source: req.source, startedAt })
      setJobState({
        phase: 'polling',
        jobId: resp.job_id,
        source: req.source,
        completed: 0,
        total: 4,
        currentPhase: null,
        startedAt,
        severityCounts: {},
      })
      startPolling(resp.job_id, req.source, startedAt)
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

  function loadSaved(report: SecurityReport) {
    setDisplayOverride({
      phase: 'done',
      jobId: report.job_id,
      source: report.source,
      findings: report.findings,
      report: report.report,
      severityCounts: report.severity_counts,
      toolsUsed: report.tools_used ?? [],
    })
  }

  function dismissOverride() {
    setDisplayOverride(null)
  }

  return { state, scan, reset, loadSaved, dismissOverride }
}
