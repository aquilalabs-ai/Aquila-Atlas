import { useState, useId, useRef } from 'react'
import { X, FolderOpen, Tag, GitBranch, FileArchive, Upload, Loader2 } from 'lucide-react'
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

interface LocalFileEntry {
  file: File
  path: string  // relative path within the folder, e.g. "src/index.ts"
}

const TABS: { key: SourceTab; label: string; icon: typeof FolderOpen }[] = [
  { key: 'local',  label: 'Local folder', icon: FolderOpen },
  { key: 'github', label: 'GitHub',       icon: GitBranch },
  { key: 'zip',    label: 'Zip upload',   icon: FileArchive },
]

// ---------------------------------------------------------------------------
// Helpers to collect files from a FileSystemDirectoryEntry (drag-and-drop)
// ---------------------------------------------------------------------------

async function readDirEntry(
  dir: FileSystemDirectoryEntry,
  prefix = '',
): Promise<LocalFileEntry[]> {
  const collected: LocalFileEntry[] = []
  const reader = dir.createReader()

  // readEntries returns at most 100 entries per call — loop until exhausted
  await new Promise<void>((resolve) => {
    function readBatch() {
      reader.readEntries(async (entries) => {
        if (entries.length === 0) {
          resolve()
          return
        }
        for (const entry of entries) {
          const relPath = prefix ? `${prefix}/${entry.name}` : entry.name
          if (entry.isFile) {
            const file = await new Promise<File>((res) =>
              (entry as FileSystemFileEntry).file(res),
            )
            collected.push({ file, path: relPath })
          } else if (entry.isDirectory) {
            const sub = await readDirEntry(entry as FileSystemDirectoryEntry, relPath)
            collected.push(...sub)
          }
        }
        readBatch()
      })
    }
    readBatch()
  })

  return collected
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RepoConnectDialog({ open, onOpenChange }: Props) {
  const repoIdId    = useId()
  const folderRef   = useRef<HTMLInputElement>(null)
  const zipFileRef  = useRef<HTMLInputElement>(null)

  const [tab,             setTab]             = useState<SourceTab>('github')
  const [localFiles,      setLocalFiles]      = useState<LocalFileEntry[] | null>(null)
  const [localFolderName, setLocalFolderName] = useState('')
  const [draggingLocal,   setDraggingLocal]   = useState(false)
  const [githubUrl,       setGitBranchUrl]    = useState('')
  const [githubToken,     setGitBranchToken]  = useState('')
  const [zipFile,         setZipFile]         = useState<File | null>(null)
  const [repoId,          setRepoId]          = useState('')
  const [jobId,           setJobId]           = useState<string | null>(null)
  const [step,            setStep]            = useState<Step>('form')
  const [submitting,      setSubmitting]      = useState(false)
  const [zipping,         setZipping]         = useState(false)
  const [formError,       setFormError]       = useState<string | null>(null)

  const qc              = useQueryClient()
  const setActiveRepoId = useAppStore((s) => s.setActiveRepoId)

  if (!open) return null

  function canSubmit(): boolean {
    if (!repoId.trim()) return false
    if (tab === 'local')  return localFiles !== null && localFiles.length > 0
    if (tab === 'github') return !!githubUrl.trim()
    if (tab === 'zip')    return zipFile !== null
    return false
  }

  // ------------------------------------------------------------------
  // Local folder — collect files from <input webkitdirectory>
  // ------------------------------------------------------------------

  function handleFolderInput(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files || files.length === 0) return

    const entries: LocalFileEntry[] = []
    let folderName = ''
    for (const file of Array.from(files)) {
      const rel = file.webkitRelativePath          // e.g. "my-repo/src/index.ts"
      if (!folderName && rel.includes('/')) {
        folderName = rel.split('/')[0]
      }
      // Keep the full relative path including the top-level folder name.
      // ZipLoader strips exactly one top-level segment, so this preserves
      // the full directory structure after upload.
      entries.push({ file, path: rel })
    }

    setLocalFiles(entries)
    setLocalFolderName(folderName)
    if (!repoId && folderName) setRepoId(folderName)
  }

  // ------------------------------------------------------------------
  // Local folder — drag-and-drop
  // ------------------------------------------------------------------

  async function handleLocalDrop(e: React.DragEvent) {
    e.preventDefault()
    setDraggingLocal(false)

    const items = Array.from(e.dataTransfer.items)
    const dirItem = items.find((i) => {
      const entry = i.webkitGetAsEntry?.()
      return entry?.isDirectory
    })

    if (!dirItem) {
      setFormError('Please drop a folder, not individual files.')
      return
    }

    const dirEntry = dirItem.webkitGetAsEntry() as FileSystemDirectoryEntry
    // Pass the folder name as prefix so paths are "folderName/src/file.ts".
    // ZipLoader strips exactly one top-level segment, preserving full structure.
    const entries = await readDirEntry(dirEntry, dirEntry.name)

    setLocalFiles(entries)
    setLocalFolderName(dirEntry.name)
    if (!repoId) setRepoId(dirEntry.name)
    setFormError(null)
  }

  // ------------------------------------------------------------------
  // Zip tab — drag-and-drop
  // ------------------------------------------------------------------

  function handleZipDrop(e: React.DragEvent) {
    e.preventDefault()
    const f = e.dataTransfer.files[0]
    if (f && (f.name.endsWith('.zip') || f.type === 'application/zip')) {
      setZipFile(f)
      if (!repoId) setRepoId(f.name.replace(/\.zip$/, ''))
    }
  }

  // ------------------------------------------------------------------
  // Submit
  // ------------------------------------------------------------------

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit()) return
    setFormError(null)
    setSubmitting(true)

    try {
      let res

      if (tab === 'local' && localFiles) {
        // Zip the folder client-side, then upload via the zip endpoint
        setZipping(true)
        const JSZip = (await import('jszip')).default
        const zip = new JSZip()
        for (const { file, path } of localFiles) {
          zip.file(path, file)
        }
        const blob = await zip.generateAsync({ type: 'blob' })
        setZipping(false)
        const zipBlob = new File([blob], `${localFolderName || repoId}.zip`, {
          type: 'application/zip',
        })
        res = await api.uploadZip(repoId.trim(), zipBlob)

      } else if (tab === 'zip' && zipFile) {
        res = await api.uploadZip(repoId.trim(), zipFile)

      } else {
        res = await api.ingest({
          repo_id:      repoId.trim(),
          source_type:  tab,
          path:         githubUrl.trim(),
          github_token: tab === 'github' ? githubToken.trim() : undefined,
        })
      }

      setJobId(res.job_id)
      setStep('ingesting')
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to start ingestion')
    } finally {
      setZipping(false)
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
      setTab('github')
      setLocalFiles(null)
      setLocalFolderName('')
      setDraggingLocal(false)
      setGitBranchUrl('')
      setGitBranchToken('')
      setZipFile(null)
      setRepoId('')
      setJobId(null)
      setFormError(null)
    }, 200)
  }

  const buttonLabel = zipping ? 'Zipping…' : submitting ? 'Starting…' : 'Start ingestion'

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

              {/* ---- LOCAL FOLDER ---- */}
              {tab === 'local' && (
                <div>
                  <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-fg-default">
                    <FolderOpen className="h-3.5 w-3.5 text-fg-muted" />
                    Local folder
                  </label>
                  <div
                    onDragOver={(e) => { e.preventDefault(); setDraggingLocal(true) }}
                    onDragLeave={() => setDraggingLocal(false)}
                    onDrop={handleLocalDrop}
                    onClick={() => folderRef.current?.click()}
                    className={cn(
                      'flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors',
                      localFiles
                        ? 'border-accent-fg bg-accent-subtle'
                        : draggingLocal
                          ? 'border-accent-fg bg-accent-subtle/40'
                          : 'border-border-default hover:border-fg-subtle',
                    )}
                  >
                    <Upload className="h-5 w-5 text-fg-subtle" />
                    {localFiles ? (
                      <div className="space-y-0.5">
                        <p className="text-xs font-medium text-fg-default">{localFolderName}/</p>
                        <p className="text-[11px] text-fg-muted">{localFiles.length} files collected</p>
                      </div>
                    ) : (
                      <p className="text-xs text-fg-muted">
                        Drop a folder here or{' '}
                        <span className="text-fg-default underline underline-offset-2">click to browse</span>
                      </p>
                    )}
                    {/* webkitdirectory lets the browser pick a whole folder */}
                    <input
                      ref={folderRef}
                      type="file"
                      // @ts-expect-error – webkitdirectory is a non-standard but widely supported attribute
                      webkitdirectory=""
                      multiple
                      className="hidden"
                      onChange={handleFolderInput}
                    />
                  </div>
                  {localFiles && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        setLocalFiles(null)
                        setLocalFolderName('')
                        if (folderRef.current) folderRef.current.value = ''
                      }}
                      className="mt-1.5 text-[11px] text-fg-subtle hover:text-fg-default transition-colors"
                    >
                      Clear selection
                    </button>
                  )}
                </div>
              )}

              {/* ---- GITHUB ---- */}
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

              {/* ---- ZIP UPLOAD ---- */}
              {tab === 'zip' && (
                <div
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={handleZipDrop}
                  onClick={() => zipFileRef.current?.click()}
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
                    ref={zipFileRef}
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
                  disabled={submitting || zipping || !canSubmit()}
                  className={cn(
                    'flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-accent-emphasis px-3 py-2 text-sm font-medium text-fg-onEmphasis transition-opacity',
                    submitting || zipping || !canSubmit()
                      ? 'cursor-not-allowed opacity-50'
                      : 'hover:opacity-90',
                  )}
                >
                  {(submitting || zipping) && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {buttonLabel}
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
