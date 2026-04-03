import { useState, useId, useRef } from 'react'
import { X, FolderOpen, Tag, GitBranch, FileArchive, Upload } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/app'
import { IngestionProgress } from './IngestionProgress'
import { cn } from '@/lib/utils'

interface Props {
  open:         boolean
  onOpenChange: (open: boolean) => void
}

type Step = 'form' | 'ingesting'
type SourceTab = 'local' | 'github' | 'zip'

const TABS: { key: SourceTab; label: string; icon: typeof FolderOpen }[] = [
  { key: 'local',  label: 'Local folder', icon: FolderOpen },
  { key: 'github', label: 'GitHub',       icon: GitBranch },
  { key: 'zip',    label: 'Zip upload',   icon: FileArchive },
]

export function RepoConnectDialog({ open, onOpenChange }: Props) {
  const repoIdId = useId()
  const fileRef  = useRef<HTMLInputElement>(null)

  const [tab,         setTab]         = useState<SourceTab>('local')
  const [localPath,   setLocalPath]   = useState('')
  const [githubUrl,   setGitBranchUrl]   = useState('')
  const [githubToken, setGitBranchToken] = useState('')
  const [zipFile,     setZipFile]     = useState<File | null>(null)
  const [repoId,      setRepoId]      = useState('')
  const [jobId,       setJobId]       = useState<string | null>(null)
  const [step,        setStep]        = useState<Step>('form')
  const [submitting,  setSubmitting]  = useState(false)
  const [formError,   setFormError]   = useState<string | null>(null)

  const qc              = useQueryClient()
  const setActiveRepoId = useAppStore((s) => s.setActiveRepoId)

  if (!open) return null

  function canSubmit(): boolean {
    if (!repoId.trim()) return false
    if (tab === 'local')  return !!localPath.trim()
    if (tab === 'github') return !!githubUrl.trim()
    if (tab === 'zip')    return zipFile !== null
    return false
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit()) return
    setFormError(null)
    setSubmitting(true)
    try {
      let res
      if (tab === 'zip' && zipFile) {
        res = await api.uploadZip(repoId.trim(), zipFile)
      } else {
        res = await api.ingest({
          repo_id:      repoId.trim(),
          source_type:  tab,
          path:         tab === 'local' ? localPath.trim() : githubUrl.trim(),
          github_token: tab === 'github' ? githubToken.trim() : undefined,
        })
      }
      setJobId(res.job_id)
      setStep('ingesting')
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to start ingestion')
    } finally {
      setSubmitting(false)
    }
  }

  function handleComplete() {
    qc.invalidateQueries({ queryKey: ['repos'] })
    setActiveRepoId(repoId)
    toast.success(`"${repoId}" is ready!`)
    dismiss()
  }

  function dismiss() {
    onOpenChange(false)
    setTimeout(() => {
      setStep('form')
      setTab('local')
      setLocalPath('')
      setGitBranchUrl('')
      setGitBranchToken('')
      setZipFile(null)
      setRepoId('')
      setJobId(null)
      setFormError(null)
    }, 200)
  }

  function handleFileDrop(e: React.DragEvent) {
    e.preventDefault()
    const f = e.dataTransfer.files[0]
    if (f && (f.name.endsWith('.zip') || f.type === 'application/zip')) {
      setZipFile(f)
      if (!repoId) setRepoId(f.name.replace(/\.zip$/, ''))
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={step === 'form' ? dismiss : undefined}
      />

      {/* Dialog panel */}
      <div className="relative z-10 w-full max-w-md rounded-2xl border border-border-default bg-canvas-overlay shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-border-default px-6 py-5">
          <div>
            <h2 className="text-sm font-semibold text-fg-default">Connect a repository</h2>
            <p className="mt-0.5 text-xs text-fg-muted">
              {step === 'form' ? 'Choose a source to index' : 'Building the knowledge graph\u2026'}
            </p>
          </div>
          {step === 'form' && (
            <button
              onClick={dismiss}
              className="rounded-lg p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          {step === 'form' ? (
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Source tabs */}
              <div className="flex rounded-lg border border-border-default p-0.5">
                {TABS.map(({ key, label, icon: Icon }) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setTab(key)}
                    className={cn(
                      'flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors',
                      tab === key
                        ? 'bg-accent-emphasis text-fg-onEmphasis'
                        : 'text-fg-muted hover:text-fg-default',
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {label}
                  </button>
                ))}
              </div>

              {/* Source-specific fields */}
              {tab === 'local' && (
                <div>
                  <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-fg-default">
                    <FolderOpen className="h-3.5 w-3.5 text-fg-muted" />
                    Local path
                  </label>
                  <input
                    type="text"
                    value={localPath}
                    onChange={(e) => setLocalPath(e.target.value)}
                    placeholder="/home/user/projects/my-service"
                    autoFocus
                    className="w-full rounded-lg border border-border-default bg-canvas-inset px-3 py-2 text-sm font-mono text-fg-default placeholder-fg-subtle outline-none transition-colors focus:border-accent-fg focus:ring-1 focus:ring-accent-fg"
                    required
                  />
                </div>
              )}

              {tab === 'github' && (
                <>
                  <div>
                    <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-fg-default">
                      <GitBranch className="h-3.5 w-3.5 text-fg-muted" />
                      Repository URL
                    </label>
                    <input
                      type="text"
                      value={githubUrl}
                      onChange={(e) => {
                        setGitBranchUrl(e.target.value)
                        // Auto-fill repo ID from URL
                        const m = e.target.value.match(/github\.com\/[^/]+\/([^/]+)/)
                        if (m && !repoId) setRepoId(m[1].replace(/\.git$/, ''))
                      }}
                      placeholder="https://github.com/owner/repo"
                      autoFocus
                      className="w-full rounded-lg border border-border-default bg-canvas-inset px-3 py-2 text-sm font-mono text-fg-default placeholder-fg-subtle outline-none transition-colors focus:border-accent-fg focus:ring-1 focus:ring-accent-fg"
                      required
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 text-xs font-medium text-fg-default">
                      GitHub token <span className="font-normal text-fg-subtle">(optional, for private repos)</span>
                    </label>
                    <input
                      type="password"
                      value={githubToken}
                      onChange={(e) => setGitBranchToken(e.target.value)}
                      placeholder="ghp_..."
                      className="w-full rounded-lg border border-border-default bg-canvas-inset px-3 py-2 text-sm font-mono text-fg-default placeholder-fg-subtle outline-none transition-colors focus:border-accent-fg focus:ring-1 focus:ring-accent-fg"
                    />
                  </div>
                </>
              )}

              {tab === 'zip' && (
                <div
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={handleFileDrop}
                  onClick={() => fileRef.current?.click()}
                  className={cn(
                    'flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors',
                    zipFile
                      ? 'border-accent-fg bg-accent-subtle'
                      : 'border-border-default hover:border-fg-subtle',
                  )}
                >
                  <Upload className="h-5 w-5 text-fg-subtle" />
                  {zipFile ? (
                    <p className="text-xs text-fg-default font-medium">{zipFile.name}</p>
                  ) : (
                    <p className="text-xs text-fg-muted">
                      Drop a <code className="text-fg-default">.zip</code> file here or click to browse
                    </p>
                  )}
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".zip"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) {
                        setZipFile(f)
                        if (!repoId) setRepoId(f.name.replace(/\.zip$/, ''))
                      }
                    }}
                  />
                </div>
              )}

              {/* Repo ID field */}
              <div>
                <label
                  htmlFor={repoIdId}
                  className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-fg-default"
                >
                  <Tag className="h-3.5 w-3.5 text-fg-muted" />
                  Repo ID
                </label>
                <input
                  id={repoIdId}
                  type="text"
                  value={repoId}
                  onChange={(e) => setRepoId(e.target.value)}
                  placeholder="my-service"
                  className="w-full rounded-lg border border-border-default bg-canvas-inset px-3 py-2 text-sm font-mono text-fg-default placeholder-fg-subtle outline-none transition-colors focus:border-accent-fg focus:ring-1 focus:ring-accent-fg"
                  required
                />
                <p className="mt-1.5 text-[11px] text-fg-subtle">
                  Short, unique identifier -- used in all API calls
                </p>
              </div>

              {/* Error */}
              {formError && (
                <div className="rounded-lg border border-danger-fg/20 bg-danger-fg/10 px-3 py-2 text-xs text-danger-fg">
                  {formError}
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-2 pt-1">
                <button
                  type="button"
                  onClick={dismiss}
                  className="flex-1 rounded-lg border border-border-default px-3 py-2 text-sm text-fg-muted transition-colors hover:bg-canvas-subtle hover:text-fg-default"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || !canSubmit()}
                  className={cn(
                    'flex-1 rounded-lg bg-accent-emphasis px-3 py-2 text-sm font-medium text-fg-onEmphasis transition-opacity',
                    submitting || !canSubmit()
                      ? 'cursor-not-allowed opacity-50'
                      : 'hover:opacity-90',
                  )}
                >
                  {submitting ? 'Starting\u2026' : 'Start ingestion'}
                </button>
              </div>
            </form>
          ) : (
            <IngestionProgress jobId={jobId!} repoId={repoId} onComplete={handleComplete} />
          )}
        </div>
      </div>
    </div>
  )
}
