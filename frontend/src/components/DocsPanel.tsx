/**
 * DocsPanel — documentation generation UI.
 *
 * Two tabs:
 *   Generate — scope/style/language form → progress bar → file browser + content viewer
 *   Saved    — list of persisted docs (with delete)
 */

import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  ArrowLeft,
  ClipboardCopy,
  Download,
  FileText,
  Folder,
  FolderOpen,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, DocContentResponse, DocLanguage, DocMetadata, DocScope, DocStyle } from '@/lib/api'
import { useDocGeneration } from '@/hooks/useDocGeneration'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Tree navigation types + builder
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
      if (i < parts.length - 1) {
        current = current[part].children!
      }
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
  const ancestors: string[] = []
  for (let i = 1; i < parts.length; i++) {
    ancestors.push(parts.slice(0, i).join('/'))
  }
  return ancestors
}

// ---------------------------------------------------------------------------
// TreeNode component
// ---------------------------------------------------------------------------

function FileTreeNode({
  node,
  depth,
  selectedFile,
  expandedFolders,
  onSelectFile,
  onToggleFolder,
}: {
  node: TreeNode
  depth: number
  selectedFile: string
  expandedFolders: Set<string>
  onSelectFile: (path: string) => void
  onToggleFolder: (path: string) => void
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
          {isExpanded ? (
            <ChevronDown className="h-3 w-3 flex-shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 flex-shrink-0" />
          )}
          {isExpanded ? (
            <FolderOpen className="h-3 w-3 flex-shrink-0 text-accent-fg" />
          ) : (
            <Folder className="h-3 w-3 flex-shrink-0 text-accent-fg" />
          )}
          <span className="truncate">{node.name}</span>
        </button>
        {isExpanded && node.children && (
          <div>
            {node.children.map((child) => (
              <FileTreeNode
                key={child.path}
                node={child}
                depth={depth + 1}
                selectedFile={selectedFile}
                expandedFolders={expandedFolders}
                onSelectFile={onSelectFile}
                onToggleFolder={onToggleFolder}
              />
            ))}
          </div>
        )}
      </div>
    )
  }

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
      <FileText className="h-3 w-3 flex-shrink-0 opacity-60" />
      <span className="truncate">{node.name}</span>
    </button>
  )
}

// ---------------------------------------------------------------------------
// DocResult — file browser + content viewer (done state)
// ---------------------------------------------------------------------------

function DocResult({
  repoId,
  jobId,
  files,
  scope,
  style,
  language,
  onBack,
}: {
  repoId: string
  jobId: string
  files: Record<string, string>
  scope: string
  style: string
  language: string
  onBack: () => void
}) {
  const tree = buildFileTree(files)
  const firstFile = Object.keys(files).sort()[0] ?? ''
  const [selectedFile, setSelectedFile] = useState(firstFile)
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(
    new Set(getAncestorPaths(firstFile)),
  )

  function handleSelectFile(path: string) {
    setSelectedFile(path)
    setExpandedFolders((prev) => new Set([...prev, ...getAncestorPaths(path)]))
  }

  function handleToggleFolder(path: string) {
    setExpandedFolders((prev) => {
      const next = new Set(prev)
      next.has(path) ? next.delete(path) : next.add(path)
      return next
    })
  }

  async function handleCopy() {
    const content = files[selectedFile] ?? ''
    try {
      await navigator.clipboard.writeText(content)
      toast.success('Copied to clipboard')
    } catch {
      toast.error('Copy failed')
    }
  }

  function handleDownload() {
    const url = api.getDocDownloadUrl(repoId, jobId)
    const a = document.createElement('a')
    a.href = url
    a.download = `${repoId}-docs-${scope}-${language}.zip`
    a.click()
  }

  const fileCount = Object.keys(files).length

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
          <span className="rounded bg-canvas-subtle px-1.5 py-0.5 text-[10px] font-medium text-fg-muted">
            {style}
          </span>
          <span className="rounded bg-canvas-subtle px-1.5 py-0.5 text-[10px] font-medium text-fg-muted">
            {language}
          </span>
          <span className="text-xs text-fg-subtle">{fileCount} file{fileCount !== 1 ? 's' : ''}</span>
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
          title="Download ZIP"
          className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default"
        >
          <Download className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Split: sidebar + content */}
      <div className="flex flex-1 overflow-hidden">
        {/* File sidebar */}
        <div className="w-52 flex-shrink-0 overflow-y-auto border-r border-border-default p-1">
          {tree.map((node) => (
            <FileTreeNode
              key={node.path}
              node={node}
              depth={0}
              selectedFile={selectedFile}
              expandedFolders={expandedFolders}
              onSelectFile={handleSelectFile}
              onToggleFolder={handleToggleFolder}
            />
          ))}
        </div>

        {/* Content viewer */}
        <div className="flex-1 overflow-y-auto p-6">
          {selectedFile && files[selectedFile] ? (
            <div className="prose-github max-w-3xl">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ className, children, ...props }) {
                    const match = /language-(\w+)/.exec(className ?? '')
                    const isBlock = !!match
                    return isBlock ? (
                      <SyntaxHighlighter
                        style={oneDark}
                        language={match[1]}
                        PreTag="div"
                        customStyle={{
                          margin: 0,
                          borderRadius: '6px',
                          fontSize: '12px',
                          lineHeight: '1.5',
                        }}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
                    ) : (
                      <code className={className} {...props}>
                        {children}
                      </code>
                    )
                  },
                }}
              >
                {files[selectedFile]}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="text-xs text-fg-subtle">Select a file to view its content</p>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Saved docs list
// ---------------------------------------------------------------------------

function SavedDocsList({
  repoId,
  onOpen,
}: {
  repoId: string
  onOpen: (content: DocContentResponse) => void
}) {
  const [docs, setDocs] = useState<DocMetadata[]>([])
  const [loading, setLoading] = useState(true)

  async function loadDocs() {
    setLoading(true)
    try {
      const resp = await api.listRepoDocs(repoId)
      setDocs(resp.docs)
    } catch {
      setDocs([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadDocs() }, [repoId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleOpen(doc: DocMetadata) {
    try {
      const content = await api.getDocContent(repoId, doc.job_id)
      onOpen(content)
    } catch {
      toast.error('Failed to load documentation')
    }
  }

  async function handleDelete(e: React.MouseEvent, doc: DocMetadata) {
    e.stopPropagation()
    try {
      await api.deleteDoc(repoId, doc.job_id)
      toast.success('Deleted')
      void loadDocs()
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

  if (docs.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
        <BookOpen className="h-8 w-8 text-fg-subtle opacity-40" />
        <p className="text-sm text-fg-muted">No saved documentation yet</p>
        <p className="text-xs text-fg-subtle">Generate docs using the Generate tab</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-1">
      {docs.map((doc) => (
        <button
          key={doc.job_id}
          onClick={() => void handleOpen(doc)}
          className="group flex w-full items-center gap-2 rounded-md border border-border-default px-3 py-2 text-left transition-colors hover:bg-canvas-subtle"
        >
          <BookOpen className="h-4 w-4 flex-shrink-0 text-accent-fg" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="rounded bg-accent-subtle px-1 py-0.5 text-[10px] font-medium text-accent-fg">
                {doc.scope}
              </span>
              <span className="rounded bg-canvas-subtle px-1 py-0.5 text-[10px] text-fg-muted">
                {doc.style}
              </span>
              <span className="rounded bg-canvas-subtle px-1 py-0.5 text-[10px] text-fg-muted">
                {doc.language}
              </span>
            </div>
            <p className="mt-0.5 text-[10px] text-fg-subtle truncate">
              {new Date(doc.created_at).toLocaleString()}
            </p>
          </div>
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => void handleDelete(e, doc)}
            onKeyDown={(e) =>
              e.key === 'Enter' && void handleDelete(e as unknown as React.MouseEvent, doc)
            }
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
// Scope / style / language options
// ---------------------------------------------------------------------------

const SCOPE_OPTIONS: { value: DocScope; label: string; description: string }[] = [
  { value: 'architecture', label: 'Architecture', description: 'Single comprehensive overview of the whole codebase' },
  { value: 'per_module', label: 'Per module', description: 'One file per top-level package with public API and dependencies' },
  { value: 'per_file', label: 'Per file', description: 'One file per source file with signatures and side-effects' },
  { value: 'subsystem', label: 'Subsystems', description: "One file per import-graph community — explains each cluster's collective purpose" },
  { value: 'flows', label: 'Execution flows', description: 'One file per entry point — traces the full call chain from public functions' },
]

const STYLE_OPTIONS: { value: DocStyle; label: string }[] = [
  { value: 'technical', label: 'Technical (developer)' },
  { value: 'functional', label: 'Functional (PM / QA)' },
]

const LANGUAGE_OPTIONS: { value: DocLanguage; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'French' },
  { value: 'es', label: 'Spanish' },
  { value: 'de', label: 'German' },
  { value: 'zh', label: 'Chinese' },
  { value: 'ja', label: 'Japanese' },
  { value: 'pt', label: 'Portuguese' },
  { value: 'ar', label: 'Arabic' },
]

// ---------------------------------------------------------------------------
// Main DocsPanel
// ---------------------------------------------------------------------------

export function DocsPanel({ repoId }: { repoId: string }) {
  const { state, generate, reset, dismissOverride, loadSaved } = useDocGeneration(repoId)
  const [activeTab, setActiveTab] = useState<'generate' | 'saved'>('generate')
  const [returnTab, setReturnTab] = useState<'generate' | 'saved'>('generate')
  const [scope, setScope] = useState<DocScope>('architecture')
  const [style, setStyle] = useState<DocStyle>('technical')
  const [language, setLanguage] = useState<DocLanguage>('en')

  // When a saved doc is opened, remember to return to saved tab (poll keeps running)
  function handleOpenSaved(content: DocContentResponse) {
    setReturnTab('saved')
    loadSaved(content)
  }

  // Done state → show DocResult
  if (state.phase === 'done') {
    function handleBack() {
      if (returnTab === 'saved') {
        // User came from saved tab: just dismiss the override so the job state is shown again
        dismissOverride()
      } else {
        // User came from a completed generation: full reset
        reset()
      }
      setActiveTab(returnTab)
      setReturnTab('generate')
    }

    return (
      <DocResult
        repoId={repoId}
        jobId={state.jobId}
        files={state.files}
        scope={state.scope}
        style={state.style}
        language={state.language}
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
          {/* Polling progress */}
          {state.phase === 'polling' && (
            <div className="mb-6 space-y-3">
              <div className="flex items-center justify-between text-xs text-fg-muted">
                <span>Generating documentation…</span>
                {state.total > 0 && (
                  <span>{state.completed}/{state.total}</span>
                )}
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-canvas-subtle">
                <div
                  className="h-full rounded-full bg-accent-emphasis transition-all duration-500"
                  style={{
                    width: state.total > 0
                      ? `${Math.round((state.completed / state.total) * 100)}%`
                      : '10%',
                  }}
                />
              </div>
              {state.currentTarget && (
                <p className="text-[11px] text-fg-subtle truncate">
                  Processing: <span className="font-mono">{state.currentTarget}</span>
                </p>
              )}
            </div>
          )}

          {/* Error */}
          {state.phase === 'error' && (
            <div className="mb-4 rounded-md border border-danger-emphasis bg-danger-subtle px-3 py-2 text-xs text-danger-fg">
              {state.message}
            </div>
          )}

          {/* Generation form */}
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

              {/* Style */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-fg-default">Style</label>
                <div className="flex gap-2">
                  {STYLE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setStyle(opt.value)}
                      className={cn(
                        'flex-1 rounded-md border py-1.5 text-xs font-medium transition-colors',
                        style === opt.value
                          ? 'border-accent-emphasis bg-accent-subtle text-accent-fg'
                          : 'border-border-default text-fg-muted hover:bg-canvas-subtle',
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Language */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-fg-default">Language</label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value as DocLanguage)}
                  className="w-full rounded-md border border-border-default bg-canvas-default px-2 py-1.5 text-xs text-fg-default focus:border-accent-emphasis focus:outline-none"
                >
                  {LANGUAGE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>

              <button
                onClick={() => void generate(scope, style, language)}
                disabled={state.phase === 'submitting'}
                className="w-full rounded-md bg-accent-emphasis py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {state.phase === 'submitting' ? 'Submitting…' : 'Generate documentation'}
              </button>
            </div>
          )}

        </div>
      )}

      {/* Saved tab */}
      {activeTab === 'saved' && (
        <SavedDocsList repoId={repoId} onOpen={handleOpenSaved} />
      )}
    </div>
  )
}
