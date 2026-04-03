import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { JobStatusKind } from '@/lib/api'

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
    mutationFn: (repoId: string) => api.deleteRepo(repoId),
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
