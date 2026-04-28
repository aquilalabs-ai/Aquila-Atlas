/**
 * TestsPanel — AI test scaffold generation UI.
 *
 * Two tabs:
 *   Generate — scope selector + optional language filter → progress → file browser + download
 *   Saved    — list of persisted test sets (with delete)
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  ClipboardCopy,
  Download,
  FileText,
  Folder,
  FolderOpen,
  FlaskConical,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, TestContentResponse, TestMetadata, TestScope } from '@/lib/api'
import { useTestGeneration } from '@/hooks/useTestGeneration'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Tree helpers (same pattern as DocsPanel)
// ---------------------------------------------------------------------------

interface TreeNode {
  name: string
  path: string
  type: 'file' | 'folder'
  children?: TreeNode[]
}

interface IntermediateNode {
  name: string
  path: string
  type: 'file' | 'folder'
  children?: Record<string, IntermediateNode>
}

function buildFileTree(files: Record<string, string>): TreeNode[] {
  const root: Record<string, IntermediateNode> = {}
  for (const filePath of Object.keys(files)) {
    const parts = filePath.replace(/\\/g, '/').split('/')
    let current = root
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      const currentPath = parts.slice(0, i + 1).join('/')
      if (!current[part]) {
        current[part] = {
          name: part,
          path: currentPath,
          type: i === parts.length - 1 ? 'file' : 'folder',
          children: i < parts.length - 1 ? {} : undefined,
        }
      }
      if (i < parts.length - 1) current = current[part].children!
    }
  }
  function toArray(obj: Record<string, IntermediateNode>): TreeNode[] {
    return Object.values(obj)
      .map((n) => ({
        name: n.name,
        path: n.path,
        type: n.type,
        children: n.children ? toArray(n.children) : undefined,
      }))
      .sort((a, b) => {
        if (a.type !== b.type) return a.type === 'folder' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
  }
  return toArray(root)
}

function getAncestorPaths(filePath: string): string[] {
  const parts = filePath.replace(/\\/g, '/').split('/')
  return parts.slice(1).map((_, i) => parts.slice(0, i + 1).join('/'))
}

// ---------------------------------------------------------------------------
// Language detection for syntax highlighting
// ---------------------------------------------------------------------------

const EXT_TO_HIGHLIGHT: Record<string, string> = {
  '.py': 'python', '.ts': 'typescript', '.tsx': 'tsx', '.js': 'javascript',
  '.jsx': 'jsx', '.java': 'java', '.go': 'go', '.rs': 'rust', '.cs': 'csharp',
  '.rb': 'ruby', '.kt': 'kotlin', '.php': 'php', '.swift': 'swift',
  '.scala': 'scala', '.bats': 'bash', '.sh': 'bash', '.cbl': 'text', '.md': 'markdown',
}

function detectHighlightLang(path: string): string {
  const ext = path.replace(/\\/g, '/').split('.').pop()
  return EXT_TO_HIGHLIGHT[`.${ext ?? ''}`] ?? 'text'
}

// ---------------------------------------------------------------------------
// FileTreeNode
// ---------------------------------------------------------------------------

function statusDotClass(status: string | undefined): string {
  if (status === 'validated')   return 'bg-success-fg'
  if (status === 'unvalidated') return 'bg-danger-fg'
  return 'bg-fg-subtle'
}

function FileTreeNode({
  node, depth, selectedFile, expandedFolders, fileStatuses, onSelectFile, onToggleFolder,
}: {
  node: TreeNode; depth: number; selectedFile: string
  expandedFolders: Set<string>; fileStatuses: Record<string, string> | null
  onSelectFile: (p: string) => void; onToggleFolder: (p: string) => void
}) {
  const isExpanded = expandedFolders.has(node.path)
  if (node.type === 'folder') {
    return (
      <div>
        <button
          onClick={() => onToggleFolder(node.path)}
          className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-xs text-fg-muted transition-colors hover:bg-canvas-subtle hover:text-fg-default"
          style={{ paddingLeft: `${depth * 12 + 4}px` }}
        >
          {isExpanded ? <ChevronDown className="h-3 w-3 flex-shrink-0" /> : <ChevronRight className="h-3 w-3 flex-shrink-0" />}
          {isExpanded
            ? <FolderOpen className="h-3 w-3 flex-shrink-0 text-accent-fg" />
            : <Folder className="h-3 w-3 flex-shrink-0 text-accent-fg" />}
          <span className="truncate">{node.name}</span>
        </button>
        {isExpanded && node.children && (
          <div>
            {node.children.map((child) => (
              <FileTreeNode key={child.path} node={child} depth={depth + 1}
                selectedFile={selectedFile} expandedFolders={expandedFolders}
                fileStatuses={fileStatuses}
                onSelectFile={onSelectFile} onToggleFolder={onToggleFolder} />
            ))}
          </div>
        )}
      </div>
    )
  }
  const dotClass = fileStatuses ? statusDotClass(fileStatuses[node.path]) : ''
  return (
    <button
      onClick={() => onSelectFile(node.path)}
      className={cn(
        'flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-xs transition-colors',
        selectedFile === node.path
          ? 'bg-accent-subtle font-medium text-accent-fg'
          : 'text-fg-muted hover:bg-canvas-subtle hover:text-fg-default',
      )}
      style={{ paddingLeft: `${depth * 12 + 4}px` }}
    >
      {fileStatuses
        ? <span className={cn('h-1.5 w-1.5 flex-shrink-0 rounded-full', dotClass)} title={fileStatuses[node.path] ?? 'syntax-only'} />
        : <span className="h-3 w-3 flex-shrink-0" />}
      <FileText className="h-3 w-3 flex-shrink-0 opacity-60" />
      <span className="truncate">{node.name}</span>
    </button>
  )
}

// ---------------------------------------------------------------------------
// PollingProgress
// ---------------------------------------------------------------------------

function PollingProgress({
  startedAt, total, completed, currentTarget, jobId, onCancel,
}: {
  startedAt: number; total: number; completed: number
  currentTarget: string | null; jobId: string; onCancel: (id: string) => Promise<void>
}) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    setNow(Date.now())
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const elapsed = Math.floor((now - startedAt) / 1000)
  const elapsedStr = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`
  let etaStr: string | null = null
  if (total > 0 && completed > 0 && completed < total) {
    const rate = elapsed / completed
    const rem = Math.round(rate * (total - completed))
    etaStr = rem < 60 ? `~${rem}s left` : `~${Math.floor(rem / 60)}m ${rem % 60}s left`
  }

  return (
    <div className="mb-6 space-y-3">
      <div className="flex items-center justify-between text-xs text-fg-muted">
        <span>Generating tests…</span>
        <span className="flex items-center gap-2">
          {total > 0 && <span>{completed}/{total}</span>}
          <span className="text-fg-subtle">{elapsedStr}</span>
          {etaStr && <span className="text-fg-subtle">{etaStr}</span>}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-canvas-subtle">
        <div
          className="h-full rounded-full bg-accent-emphasis transition-all duration-500"
          style={{ width: total > 0 ? `${Math.round((completed / total) * 100)}%` : '10%' }}
        />
      </div>
      {currentTarget && (
        <p className="text-[11px] text-fg-subtle truncate">
          Processing: <span className="font-mono">{currentTarget}</span>
        </p>
      )}
      <button
        type="button"
        onClick={() => void onCancel(jobId)}
        className="mt-1 flex items-center gap-1.5 rounded-md border border-danger-emphasis/40 px-2.5 py-1 text-xs text-danger-fg transition-colors hover:bg-danger-subtle"
      >
        <X className="h-3 w-3" />
        Cancel generation
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TestResult — file browser + code viewer + download button
// ---------------------------------------------------------------------------

function statusBadgeProps(status: string | null | undefined): { label: string; className: string } {
  switch (status) {
    case 'validated':   return { label: 'validated', className: 'bg-success-subtle text-success-fg' }
    case 'unvalidated': return { label: 'unvalidated', className: 'bg-danger-subtle text-danger-fg' }
    default:            return { label: status ?? 'syntax-only', className: 'bg-accent-subtle text-accent-fg' }
  }
}

function TestResult({
  repoId, jobId, files, fileStatuses, scope, onBack,
}: {
  repoId: string; jobId: string; files: Record<string, string>; fileStatuses: Record<string, string> | null; scope: string; onBack: () => void
}) {
  const tree = useMemo(() => buildFileTree(files), [files])
  const firstFile = useMemo(() => Object.keys(files).sort()[0] ?? '', [files])
  const [selectedFile, setSelectedFile] = useState(firstFile)
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set(getAncestorPaths(firstFile)))

  const handleSelectFile = useCallback((path: string) => {
    setSelectedFile(path)
    setExpandedFolders((prev) => new Set([...prev, ...getAncestorPaths(path)]))
  }, [])

  const handleToggleFolder = useCallback((path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev)
      next.has(path) ? next.delete(path) : next.add(path)
      return next
    })
  }, [])

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(files[selectedFile] ?? '')
      toast.success('Copied to clipboard')
    } catch {
      toast.error('Copy failed')
    }
  }

  function handleDownload() {
    const url = api.getTestDownloadUrl(repoId, jobId)
    const a = document.createElement('a')
    a.href = url
    a.download = `${repoId}-tests-${scope}.zip`
    a.click()
  }

  const fileCount = Object.keys(files).length
  const hlLang = detectHighlightLang(selectedFile)

  // Resolve per-file status: use validated statuses dict first, fall back to AQUILA header
  const resolveStatus = (path: string): string | null => {
    if (fileStatuses && path in fileStatuses) return fileStatuses[path]
    const c = files[path] ?? ''
    const line = c.split('\n').find((l) => l.includes('[AQUILA]') && l.includes('status:'))
    return line?.split('status:')[1]?.trim() ?? null
  }

  const content = files[selectedFile] ?? ''
  const currentStatus = resolveStatus(selectedFile)
  const badge = statusBadgeProps(currentStatus)

  // Summary counts for the toolbar
  const statusCounts = useMemo(() => {
    const counts = { validated: 0, 'syntax-only': 0, unvalidated: 0 }
    for (const path of Object.keys(files)) {
      const s = resolveStatus(path) ?? 'syntax-only'
      if (s in counts) counts[s as keyof typeof counts]++
      else counts['syntax-only']++
    }
    return counts
  }, [files, fileStatuses]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex h-10 flex-shrink-0 items-center gap-2 border-b border-border-default px-3">
        <button
          onClick={onBack}
          title="Back"
          className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
        </button>
        <div className="flex flex-1 items-center gap-2">
          <span className="rounded bg-canvas-subtle px-1.5 py-0.5 text-[10px] font-medium text-fg-muted">
            {scope}
          </span>
          <span className="text-xs text-fg-subtle">
            {fileCount} file{fileCount !== 1 ? 's' : ''}
          </span>
          {statusCounts.validated > 0 && (
            <span className="rounded bg-success-subtle px-1.5 py-0.5 text-[10px] font-medium text-success-fg">
              {statusCounts.validated} validated
            </span>
          )}
          {statusCounts.unvalidated > 0 && (
            <span className="rounded bg-danger-subtle px-1.5 py-0.5 text-[10px] font-medium text-danger-fg">
              {statusCounts.unvalidated} unvalidated
            </span>
          )}
          {currentStatus && (
            <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-medium', badge.className)}>
              {badge.label}
            </span>
          )}
        </div>
        <button
          onClick={() => void handleCopy()}
          title="Copy current file"
          className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default"
        >
          <ClipboardCopy className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={handleDownload}
          title="Download ZIP (with README + annotated headers)"
          className="flex items-center gap-1 rounded-md border border-border-default px-2 py-1 text-xs text-fg-default transition-colors hover:bg-canvas-subtle"
        >
          <Download className="h-3.5 w-3.5" />
          <span>Download ZIP</span>
        </button>
      </div>

      {/* Split: sidebar + code viewer */}
      <div className="flex flex-1 overflow-hidden">
        {/* File sidebar */}
        <div className="flex w-52 flex-shrink-0 flex-col overflow-y-auto border-r border-border-default p-1">
          {tree.map((node) => (
            <FileTreeNode
              key={node.path}
              node={node}
              depth={0}
              selectedFile={selectedFile}
              expandedFolders={expandedFolders}
              fileStatuses={fileStatuses}
              onSelectFile={handleSelectFile}
              onToggleFolder={handleToggleFolder}
            />
          ))}
        </div>

        {/* Code viewer */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {selectedFile ? (
            <div className="flex-1 overflow-auto">
              <SyntaxHighlighter
                language={hlLang}
                style={oneDark}
                showLineNumbers
                wrapLongLines={false}
                customStyle={{ margin: 0, borderRadius: 0, fontSize: '12px', lineHeight: '1.5', minHeight: '100%' }}
              >
                {content}
              </SyntaxHighlighter>
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-xs text-fg-subtle">Select a file to view its content</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SavedTestsList
// ---------------------------------------------------------------------------

function SavedTestsList({
  repoId, onOpen,
}: {
  repoId: string; onOpen: (content: TestContentResponse) => void
}) {
  const [tests, setTests] = useState<TestMetadata[]>([])
  const [loading, setLoading] = useState(true)

  async function loadTests() {
    setLoading(true)
    try {
      const resp = await api.listRepoTests(repoId)
      setTests(resp.tests)
    } catch {
      setTests([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadTests() }, [repoId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleOpen(test: TestMetadata) {
    try {
      const content = await api.getTestContent(repoId, test.job_id)
      onOpen(content)
    } catch {
      toast.error('Failed to load test content')
    }
  }

  async function handleDelete(e: React.MouseEvent, test: TestMetadata) {
    e.stopPropagation()
    try {
      await api.deleteTest(repoId, test.job_id)
      toast.success('Deleted')
      void loadTests()
    } catch {
      toast.error('Delete failed')
    }
  }

  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-md bg-canvas-subtle" />
        ))}
      </div>
    )
  }

  if (tests.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
        <FlaskConical className="h-8 w-8 text-fg-subtle opacity-40" />
        <p className="text-sm text-fg-muted">No saved test sets yet</p>
        <p className="text-xs text-fg-subtle">Generate tests using the Generate tab</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-1">
      {tests.map((test) => (
        <button
          key={test.job_id}
          onClick={() => void handleOpen(test)}
          className="group flex w-full items-center gap-2 rounded-md border border-border-default px-3 py-2 text-left transition-colors hover:bg-canvas-subtle"
        >
          <FlaskConical className="h-4 w-4 flex-shrink-0 text-accent-fg" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="rounded bg-accent-subtle px-1 py-0.5 text-[10px] font-medium text-accent-fg">
                {test.scope}
              </span>
              {test.language_filter && test.language_filter.length > 0 && (
                <span className="rounded bg-canvas-subtle px-1 py-0.5 text-[10px] text-fg-muted">
                  {test.language_filter.join(', ')}
                </span>
              )}
            </div>
            <p className="mt-0.5 text-[10px] text-fg-subtle truncate">
              {new Date(test.created_at).toLocaleString()}
            </p>
          </div>
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => void handleDelete(e, test)}
            onKeyDown={(e) => e.key === 'Enter' && void handleDelete(e as unknown as React.MouseEvent, test)}
            className="hidden rounded p-1 text-danger-fg transition-colors hover:bg-canvas-default group-hover:block"
            title="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </span>
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Scope options
// ---------------------------------------------------------------------------

const SCOPE_OPTIONS: { value: TestScope; label: string; description: string }[] = [
  { value: 'per_file', label: 'Per file', description: 'One test file per source file — maximum coverage' },
  { value: 'per_module', label: 'Per module', description: 'One test file per package / module — balanced coverage' },
  { value: 'entry_points', label: 'Entry points', description: 'Tests for public functions with no callers — critical paths only' },
]

const LANGUAGE_OPTIONS = [
  { value: 'python', label: 'Python' },
  { value: 'typescript', label: 'TypeScript' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'java', label: 'Java' },
  { value: 'go', label: 'Go' },
  { value: 'rust', label: 'Rust' },
  { value: 'c#', label: 'C#' },
  { value: 'ruby', label: 'Ruby' },
  { value: 'kotlin', label: 'Kotlin' },
  { value: 'php', label: 'PHP' },
  { value: 'swift', label: 'Swift' },
  { value: 'scala', label: 'Scala' },
]

// ---------------------------------------------------------------------------
// Main TestsPanel
// ---------------------------------------------------------------------------

export function TestsPanel({ repoId }: { repoId: string }) {
  const { state, generate, reset, cancel, dismissOverride, loadSaved } = useTestGeneration(repoId)
  const [activeTab, setActiveTab] = useState<'generate' | 'saved'>('generate')
  const [returnTab, setReturnTab] = useState<'generate' | 'saved'>('generate')
  const [scope, setScope] = useState<TestScope>('per_file')
  const [selectedLangs, setSelectedLangs] = useState<Set<string>>(new Set())

  function toggleLang(lang: string) {
    setSelectedLangs((prev) => {
      const next = new Set(prev)
      next.has(lang) ? next.delete(lang) : next.add(lang)
      return next
    })
  }

  function handleOpenSaved(content: TestContentResponse) {
    setReturnTab('saved')
    loadSaved(content)
  }

  if (state.phase === 'done') {
    function handleBack() {
      if (returnTab === 'saved') {
        dismissOverride()
      } else {
        reset()
      }
      setActiveTab(returnTab)
      setReturnTab('generate')
    }
    return (
      <TestResult
        repoId={repoId}
        jobId={state.jobId}
        files={state.files}
        fileStatuses={state.fileStatuses}
        scope={state.scope}
        onBack={handleBack}
      />
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex h-10 flex-shrink-0 items-center gap-0 border-b border-border-default px-3">
        {(['generate', 'saved'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-3 py-1.5 text-xs font-medium transition-colors capitalize',
              activeTab === tab
                ? 'border-b-2 border-accent-emphasis text-accent-fg'
                : 'text-fg-muted hover:text-fg-default',
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Generate tab */}
      {activeTab === 'generate' && (
        <div className="flex-1 overflow-y-auto p-4">
          {state.phase === 'polling' && (
            <PollingProgress
              startedAt={state.startedAt}
              total={state.total}
              completed={state.completed}
              currentTarget={state.currentTarget}
              jobId={state.jobId}
              onCancel={cancel}
            />
          )}

          {state.phase === 'error' && (
            <div className="mb-4 rounded-md border border-danger-emphasis bg-danger-subtle px-3 py-2 text-xs text-danger-fg">
              {state.message}
            </div>
          )}

          {(state.phase === 'idle' || state.phase === 'error' || state.phase === 'submitting') && (
            <div className="space-y-5">
              {/* Scope */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-fg-default">Scope</label>
                <div className="space-y-1.5">
                  {SCOPE_OPTIONS.map((opt) => (
                    <label
                      key={opt.value}
                      className={cn(
                        'flex cursor-pointer items-start gap-2.5 rounded-md border p-2.5 transition-colors',
                        scope === opt.value
                          ? 'border-accent-emphasis bg-accent-subtle'
                          : 'border-border-default hover:bg-canvas-subtle',
                      )}
                    >
                      <input
                        type="radio"
                        name="scope"
                        value={opt.value}
                        checked={scope === opt.value}
                        onChange={() => setScope(opt.value)}
                        className="mt-0.5 accent-accent-emphasis"
                      />
                      <div>
                        <p className="text-xs font-medium text-fg-default">{opt.label}</p>
                        <p className="text-[10px] text-fg-subtle">{opt.description}</p>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              {/* Language filter */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-fg-default">
                  Languages <span className="font-normal text-fg-subtle">(leave empty for all detected)</span>
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {LANGUAGE_OPTIONS.map((opt) => {
                    const active = selectedLangs.has(opt.value)
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => toggleLang(opt.value)}
                        className={cn(
                          'rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors',
                          active
                            ? 'border-accent-emphasis bg-accent-subtle text-accent-fg'
                            : 'border-border-default text-fg-subtle hover:border-fg-subtle hover:text-fg-default',
                        )}
                      >
                        {opt.label}
                      </button>
                    )
                  })}
                </div>
                {selectedLangs.size > 0 && (
                  <button
                    type="button"
                    onClick={() => setSelectedLangs(new Set())}
                    className="mt-1.5 text-[10px] text-fg-subtle underline hover:text-fg-default"
                  >
                    Clear filter
                  </button>
                )}
              </div>

              <button
                onClick={() => void generate(scope, selectedLangs.size > 0 ? [...selectedLangs] : null)}
                disabled={state.phase === 'submitting'}
                className="w-full rounded-md bg-accent-emphasis py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {state.phase === 'submitting' ? 'Submitting…' : 'Generate tests'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Saved tab */}
      {activeTab === 'saved' && (
        <SavedTestsList repoId={repoId} onOpen={handleOpenSaved} />
      )}
    </div>
  )
}
