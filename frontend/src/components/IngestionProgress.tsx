import { useEffect } from 'react'
import { CheckCircle2, XCircle, Loader2, FileCode2, Boxes } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useJobStatus } from '@/hooks/useRepos'

interface Props {
  jobId:      string
  repoId:     string
  onComplete: () => void
}

export function IngestionProgress({ jobId, repoId, onComplete }: Props) {
  const { data: job } = useJobStatus(jobId, true)
  const qc = useQueryClient()

  const status    = job?.status ?? 'queued'
  const isRunning = status === 'queued' || status === 'running'
  const isDone    = status === 'done'
  const isFailed  = status === 'failed'

  // Refresh repo list immediately when done, then brief pause before closing
  useEffect(() => {
    if (!isDone) return
    qc.invalidateQueries({ queryKey: ['repos'] })
    const t = setTimeout(onComplete, 900)
    return () => clearTimeout(t)
  }, [isDone, onComplete, qc])

  return (
    <div className="space-y-5">
      {/* Status row */}
      <div className="flex items-start gap-3">
        {isRunning && (
          <Loader2 className="mt-0.5 h-5 w-5 flex-shrink-0 animate-spin text-accent-fg" />
        )}
        {isDone && (
          <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-success-fg" />
        )}
        {isFailed && (
          <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-danger-fg" />
        )}
        <div>
          <p className="text-sm font-medium text-fg-default">
            {status === 'queued'  && 'Waiting in queue…'}
            {status === 'running' && 'Indexing your codebase…'}
            {status === 'done'    && 'Ready!'}
            {status === 'failed'  && 'Ingestion failed'}
          </p>
          <p className="text-xs text-fg-muted">{repoId}</p>
        </div>
      </div>

      {/* Indeterminate progress bar while running */}
      {isRunning && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-border-muted">
          <div className="h-full w-1/4 animate-indeterminate rounded-full bg-accent-emphasis" />
        </div>
      )}

      {/* Stats once done */}
      {isDone && job && (
        <div className="flex gap-5">
          <div className="flex items-center gap-1.5 text-xs text-fg-muted">
            <FileCode2 className="h-3.5 w-3.5" />
            <span>{job.files ?? 0} files indexed</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-fg-muted">
            <Boxes className="h-3.5 w-3.5" />
            <span>{job.chunks ?? 0} chunks stored</span>
          </div>
        </div>
      )}

      {/* Error */}
      {isFailed && (
        <pre className="overflow-x-auto rounded-lg border border-danger-fg/20 bg-danger-fg/10 px-3 py-2 text-xs text-danger-fg font-mono whitespace-pre-wrap">
          {job?.error ?? 'Unknown error'}
        </pre>
      )}
    </div>
  )
}
