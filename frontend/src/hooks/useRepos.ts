import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect, useCallback } from 'react'
import { api } from '@/lib/api'
import type { JobStatus, JobStatusKind } from '@/lib/api'
import type { RepoSource } from '@/store/app'

export type ResyncPhase = 'idle' | 'running' | 'done' | 'error'

export interface ResyncState {
  phase: ResyncPhase
  result: JobStatus | null
  start: (source: RepoSource) => Promise<void>
  reset: () => void
}

export function useRepoList() {
  return useQuery({
    queryKey: ['repos'],
    queryFn: () => api.listRepos(),
    refetchInterval: 5_000,
  })
}

export function useRepoStats(repoId: string | null) {
  return useQuery({
    queryKey: ['repos', repoId, 'stats'],
    queryFn: () => api.getRepoStats(repoId!),
    enabled: repoId !== null,
  })
}

export function useDeleteRepo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ repoId, deleteSessions, deleteDocs }: { repoId: string; deleteSessions?: boolean; deleteDocs?: boolean }) =>
      api.deleteRepo(repoId, { deleteSessions, deleteDocs }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['repos'] }),
  })
}

const TERMINAL: JobStatusKind[] = ['done', 'failed']

export function useJobStatus(jobId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['jobs', jobId],
    queryFn: () => api.getJob(jobId!),
    enabled: enabled && jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && TERMINAL.includes(status) ? false : 2_000
    },
  })
}

export function useResyncRepo(repoId: string): ResyncState {
  const [phase, setPhase] = useState<ResyncPhase>('idle')
  const [jobId, setJobId] = useState<string | null>(null)
  const [result, setResult] = useState<JobStatus | null>(null)

  const polling = phase === 'running' && jobId !== null
  const { data } = useQuery({
    queryKey: ['jobs', jobId],
    queryFn: () => api.getJob(jobId!),
    enabled: polling,
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return s && TERMINAL.includes(s) ? false : 2_000
    },
  })

  useEffect(() => {
    if (!data) return
    if (data.status === 'done' || data.status === 'failed') {
      setResult(data)
      setPhase(data.status === 'done' ? 'done' : 'error')
    }
  }, [data])

  const start = useCallback(async (source: RepoSource) => {
    setPhase('running')
    setResult(null)
    setJobId(null)
    try {
      const resp = await api.resyncRepo(repoId, {
        path: source.path,
        source_type: source.source_type,
        github_token: source.github_token,
      })
      setJobId(resp.job_id)
    } catch (err) {
      setResult({ job_id: '', repo_id: repoId, status: 'failed', error: String(err) })
      setPhase('error')
    }
  }, [repoId])

  const reset = useCallback(() => {
    setPhase('idle')
    setJobId(null)
    setResult(null)
  }, [])

  return { phase, result, start, reset }
}
