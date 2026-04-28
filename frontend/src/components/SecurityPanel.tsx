/**
 * SecurityPanel — AI-assisted security scanning UI.
 *
 * Two tabs:
 *   Scan    — form + progress + findings grouped by severity
 *   History — list of past scans
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  ClipboardCopy,
  ExternalLink,
  FileSearch,
  RotateCcw,
  Shield,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, SecurityFinding, SecurityReport, SecurityScanMeta } from '@/lib/api'
import { useSecurityScan } from '@/hooks/useSecurityScan'
import { useAppStore } from '@/store/app'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Severity config
// ---------------------------------------------------------------------------

const SEV_ORDER: Array<SecurityFinding['severity']> = ['critical', 'major', 'minor']

const SEV_CONFIG = {
  critical: {
    label: 'Critical',
    icon: '🔴',
    badge: 'bg-danger-subtle text-danger-fg border-danger-emphasis/30',
    header: 'bg-danger-subtle/50 border-danger-emphasis/20',
    dot: 'bg-red-500',
  },
  major: {
    label: 'Major',
    icon: '🟠',
    badge: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-400 dark:border-amber-700/30',
    header: 'bg-amber-50/50 border-amber-200/50 dark:bg-amber-900/10 dark:border-amber-700/20',
    dot: 'bg-amber-500',
  },
  minor: {
    label: 'Minor',
    icon: '🔵',
    badge: 'bg-accent-subtle text-accent-fg border-border-default',
    header: 'bg-accent-subtle/30 border-border-default',
    dot: 'bg-blue-500',
  },
} as const

const SEMGREP_CONFIGS = [
  { value: 'auto', label: 'auto (recommended)' },
  { value: 'p/owasp-top-ten', label: 'OWASP Top Ten' },
  { value: 'p/security-audit', label: 'Security Audit' },
  { value: 'p/secrets', label: 'Secrets Detection' },
  { value: 'p/python', label: 'Python rules' },
  { value: 'p/javascript', label: 'JavaScript rules' },
  { value: 'p/typescript', label: 'TypeScript rules' },
  { value: 'p/java', label: 'Java rules' },
  { value: 'p/go', label: 'Go rules' },
]

// ---------------------------------------------------------------------------
// Badge counts helper
// ---------------------------------------------------------------------------

function SeverityBadges({ counts }: { counts: Record<string, number> }) {
  return (
    <span className="flex items-center gap-1.5">
      {SEV_ORDER.map((sev) => {
        const n = counts[sev] ?? 0
        if (n === 0) return null
        return (
          <span
            key={sev}
            className={cn(
              'rounded border px-1.5 py-0.5 text-[10px] font-medium',
              SEV_CONFIG[sev].badge,
            )}
          >
            {SEV_CONFIG[sev].icon} {n}
          </span>
        )
      })}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Scan form
// ---------------------------------------------------------------------------

interface ScanFormProps {
  repoId: string
  onSubmit: (source: string, token: string, config: string, llm: boolean) => void
}

function ScanForm({ repoId, onSubmit }: ScanFormProps) {
  const repoSource = useAppStore((s) => s.repoSources[repoId])
  const [config, setConfig] = useState('auto')
  const [llm, setLlm] = useState(true)
  const [customConfig, setCustomConfig] = useState('')
  // Fallback manual path (only shown when no repoSource is available and backend fetch fails)
  const [manualSource, setManualSource] = useState('')
  // Source fetched from the backend for repos ingested via CLI or before store was populated
  const [backendSource, setBackendSource] = useState<{ path: string; source_type: string } | null>(null)
  const fetchedRef = useRef(false)

  useEffect(() => {
    if (repoSource || fetchedRef.current) return
    fetchedRef.current = true
    api.getRepoSource(repoId)
      .then((s) => setBackendSource({ path: s.path, source_type: s.source_type }))
      .catch(() => {/* repo not found or no job — fall through to manual input */})
  }, [repoId, repoSource])

  const effectiveSource = repoSource ?? (backendSource ? { ...backendSource, github_token: undefined } : null)
  const resolvedSource = effectiveSource?.path ?? manualSource
  const resolvedToken  = repoSource?.github_token ?? ''

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const finalConfig = config === '__custom__' ? customConfig.trim() : config
    if (!resolvedSource.trim() || !finalConfig) return
    onSubmit(resolvedSource.trim(), resolvedToken, finalConfig, llm)
  }

  const sourceTypeLabel: Record<string, string> = {
    local: 'local path',
    github: 'GitHub',
    gitlab: 'GitLab',
    gitea: 'Gitea',
    git: 'git remote',
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto w-full max-w-lg space-y-4 py-8 px-4">
      <div className="flex items-center gap-2 text-sm font-medium text-fg-default">
        <Shield className="h-4 w-4 text-accent-fg" />
        Security Scan
      </div>

      {/* Source — derived from the repo, shown as read-only info */}
      <div className="space-y-1">
        <span className="text-xs font-medium text-fg-muted">Scan target</span>
        {effectiveSource ? (
          <div className="flex items-center gap-2 rounded-md border border-border-default bg-canvas-subtle px-3 py-1.5">
            <span className="rounded bg-accent-subtle px-1.5 py-0.5 text-[10px] font-medium text-accent-fg">
              {sourceTypeLabel[effectiveSource.source_type] ?? effectiveSource.source_type}
            </span>
            <span className="flex-1 truncate font-mono text-[11px] text-fg-default" title={effectiveSource.path}>
              {effectiveSource.path}
            </span>
            {resolvedToken && (
              <span className="text-[10px] text-fg-subtle">🔑 token</span>
            )}
          </div>
        ) : (
          <input
            type="text"
            value={manualSource}
            onChange={(e) => setManualSource(e.target.value)}
            placeholder="/path/to/project  or  https://github.com/owner/repo"
            className="w-full rounded-md border border-border-default bg-canvas-subtle px-3 py-1.5 text-xs text-fg-default placeholder:text-fg-subtle focus:border-accent-emphasis focus:outline-none"
          />
        )}
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-fg-muted">Semgrep rule set</label>
        <select
          value={config}
          onChange={(e) => setConfig(e.target.value)}
          className="w-full rounded-md border border-border-default bg-canvas-subtle px-3 py-1.5 text-xs text-fg-default focus:border-accent-emphasis focus:outline-none"
        >
          {SEMGREP_CONFIGS.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
          <option value="__custom__">Custom rule…</option>
        </select>
        {config === '__custom__' && (
          <input
            type="text"
            value={customConfig}
            onChange={(e) => setCustomConfig(e.target.value)}
            placeholder="e.g. p/cwe-top-25 or path/to/rules.yaml"
            className="mt-1 w-full rounded-md border border-border-default bg-canvas-subtle px-3 py-1.5 text-xs text-fg-default placeholder:text-fg-subtle focus:border-accent-emphasis focus:outline-none"
          />
        )}
      </div>

      <label className="flex cursor-pointer items-center gap-2 text-xs text-fg-muted">
        <input
          type="checkbox"
          checked={llm}
          onChange={(e) => setLlm(e.target.checked)}
          className="rounded"
        />
        LLM triage (generates fix suggestions)
      </label>

      <button
        type="submit"
        disabled={!resolvedSource.trim()}
        className="flex w-full items-center justify-center gap-2 rounded-md bg-accent-emphasis px-4 py-2 text-xs font-medium text-white transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <FileSearch className="h-3.5 w-3.5" />
        Start Scan
      </button>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Scan progress
// ---------------------------------------------------------------------------

const PHASE_LABELS = [
  'Resolving source…',
  'Running Semgrep…',
  'LLM triage…',
  'Building report…',
]

function ScanProgress({
  completed, total, currentPhase, startedAt, onCancel,
}: {
  completed: number; total: number; currentPhase: string | null
  startedAt: number; onCancel: () => void
}) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const elapsed = Math.floor((now - startedAt) / 1000)
  const elapsedStr = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`
  const pct = total > 0 ? Math.round((completed / total) * 100) : 15
  const phase = currentPhase ?? PHASE_LABELS[Math.min(completed, PHASE_LABELS.length - 1)]

  return (
    <div className="mx-auto w-full max-w-lg space-y-4 py-8 px-4">
      <div className="flex items-center justify-between text-xs text-fg-muted">
        <span className="flex items-center gap-1.5">
          <Shield className="h-3.5 w-3.5 text-accent-fg" />
          Scanning…
        </span>
        <span>{elapsedStr}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-canvas-subtle">
        <div
          className="h-full rounded-full bg-accent-emphasis transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-[11px] text-fg-subtle truncate">{phase}</p>
      <div className="flex items-center justify-between text-[10px] text-fg-subtle">
        <span>{completed}/{total} phases</span>
        <button
          type="button"
          onClick={onCancel}
          className="flex items-center gap-1 rounded border border-danger-emphasis/40 px-2 py-0.5 text-danger-fg hover:bg-danger-subtle"
        >
          <X className="h-3 w-3" />
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

interface FilterState {
  severities: Set<SecurityFinding['severity']>
  owasp: string
  fileSearch: string
}

function FilterBar({
  findings,
  filters,
  onChange,
}: {
  findings: SecurityFinding[]
  filters: FilterState
  onChange: (f: FilterState) => void
}) {
  const owaspOptions = useMemo(() => {
    const cats = new Set<string>()
    for (const f of findings) if (f.owasp_category) cats.add(f.owasp_category)
    return Array.from(cats).sort()
  }, [findings])

  function toggleSev(sev: SecurityFinding['severity']) {
    const next = new Set(filters.severities)
    next.has(sev) ? next.delete(sev) : next.add(sev)
    onChange({ ...filters, severities: next })
  }

  return (
    <div className="flex flex-shrink-0 flex-wrap items-center gap-2 border-b border-border-default px-3 py-1.5">
      <span className="text-[10px] font-medium text-fg-subtle uppercase tracking-wide">Filter:</span>
      {SEV_ORDER.map((sev) => (
        <button
          key={sev}
          onClick={() => toggleSev(sev)}
          className={cn(
            'rounded border px-1.5 py-0.5 text-[10px] font-medium transition-opacity',
            SEV_CONFIG[sev].badge,
            !filters.severities.has(sev) && 'opacity-30',
          )}
        >
          {SEV_CONFIG[sev].icon} {SEV_CONFIG[sev].label}
        </button>
      ))}
      {owaspOptions.length > 0 && (
        <select
          value={filters.owasp}
          onChange={(e) => onChange({ ...filters, owasp: e.target.value })}
          className="rounded border border-border-default bg-canvas-subtle px-2 py-0.5 text-[10px] text-fg-muted focus:outline-none"
        >
          <option value="">All OWASP</option>
          {owaspOptions.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      )}
      <input
        type="text"
        value={filters.fileSearch}
        onChange={(e) => onChange({ ...filters, fileSearch: e.target.value })}
        placeholder="filter by file…"
        className="flex-1 min-w-[120px] rounded border border-border-default bg-canvas-subtle px-2 py-0.5 text-[10px] text-fg-default placeholder:text-fg-subtle focus:outline-none"
      />
      {(filters.owasp || filters.fileSearch || filters.severities.size < 3) && (
        <button
          onClick={() => onChange({ severities: new Set(SEV_ORDER), owasp: '', fileSearch: '' })}
          className="text-[10px] text-fg-subtle hover:text-fg-default"
          title="Clear filters"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Finding card
// ---------------------------------------------------------------------------

function FindingCard({
  finding,
  repoId,
}: {
  finding: SecurityFinding
  repoId: string
}) {
  const [expanded, setExpanded] = useState(false)
  const openSource = useAppStore((s) => s.openSource)

  async function handleCopyFix() {
    try {
      await navigator.clipboard.writeText(finding.fix_suggestion)
      toast.success('Fix suggestion copied')
    } catch {
      toast.error('Copy failed')
    }
  }

  function handleFileClick() {
    openSource({ repoId, filePath: finding.file, line: finding.line })
  }

  return (
    <div className="rounded-md border border-border-default bg-canvas-default overflow-hidden">
      {/* Card header — always visible */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-canvas-subtle"
      >
        <span className="mt-0.5 flex-shrink-0">
          {expanded
            ? <ChevronDown className="h-3.5 w-3.5 text-fg-subtle" />
            : <ChevronRight className="h-3.5 w-3.5 text-fg-subtle" />}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-[10px] text-fg-subtle truncate">{finding.rule_id}</span>
            {finding.confirmed_by_llm && (
              <span className="rounded bg-success-subtle px-1 py-0.5 text-[9px] font-medium text-success-fg">
                LLM confirmed
              </span>
            )}
          </div>
          <p className="text-xs text-fg-default leading-snug">{finding.message}</p>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); handleFileClick() }}
          className="ml-auto flex flex-shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-mono text-accent-fg hover:bg-accent-subtle"
          title="Open in source viewer"
        >
          <ExternalLink className="h-3 w-3" />
          {finding.file.split('/').pop()}:{finding.line}
        </button>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-border-default px-3 py-2 space-y-2 bg-canvas-subtle/50">
          <div className="flex flex-wrap gap-3 text-[10px] text-fg-muted">
            <span><span className="text-fg-subtle">File:</span> <span className="font-mono">{finding.file}:{finding.line}</span></span>
            <span><span className="text-fg-subtle">Source:</span> {finding.source}</span>
            {finding.cwe && <span><span className="text-fg-subtle">CWE:</span> {finding.cwe}</span>}
            {finding.owasp_category && <span><span className="text-fg-subtle">OWASP:</span> {finding.owasp_category}</span>}
          </div>

          {finding.fix_suggestion && (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-medium text-fg-subtle">Fix suggestion</span>
                <button
                  onClick={() => void handleCopyFix()}
                  className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-fg-muted hover:bg-canvas-subtle hover:text-fg-default"
                >
                  <ClipboardCopy className="h-3 w-3" />
                  Copy
                </button>
              </div>
              <p className="text-[11px] text-fg-default leading-relaxed whitespace-pre-wrap">
                {finding.fix_suggestion}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Findings group
// ---------------------------------------------------------------------------

function FindingsGroup({
  severity,
  findings,
  repoId,
}: {
  severity: SecurityFinding['severity']
  findings: SecurityFinding[]
  repoId: string
}) {
  const [collapsed, setCollapsed] = useState(false)
  const cfg = SEV_CONFIG[severity]

  if (findings.length === 0) return null

  return (
    <div className="overflow-hidden rounded-lg border border-border-default">
      <button
        onClick={() => setCollapsed((v) => !v)}
        className={cn(
          'flex w-full items-center gap-2 border-b px-3 py-2 text-left',
          cfg.header,
        )}
      >
        {collapsed
          ? <ChevronRight className="h-3.5 w-3.5 text-fg-subtle flex-shrink-0" />
          : <ChevronDown className="h-3.5 w-3.5 text-fg-subtle flex-shrink-0" />}
        <span className="text-sm">{cfg.icon}</span>
        <span className="text-xs font-semibold text-fg-default">{cfg.label}</span>
        <span className={cn('ml-1 rounded border px-1.5 py-0.5 text-[10px] font-medium', cfg.badge)}>
          {findings.length}
        </span>
      </button>
      {!collapsed && (
        <div className="divide-y divide-border-default">
          {findings.map((f, i) => (
            <FindingCard key={`${f.file}:${f.line}:${f.rule_id}:${i}`} finding={f} repoId={repoId} />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Scan results
// ---------------------------------------------------------------------------

function ScanResults({
  repoId,
  source,
  findings,
  report,
  severityCounts,
  toolsUsed,
  onReset,
}: {
  repoId: string
  source: string
  findings: SecurityFinding[]
  report: string
  severityCounts: Record<string, number>
  toolsUsed: string[]
  onReset: () => void
}) {
  const [filters, setFilters] = useState<FilterState>({
    severities: new Set(SEV_ORDER),
    owasp: '',
    fileSearch: '',
  })
  const [showReport, setShowReport] = useState(false)

  const filtered = useMemo(() => {
    return findings.filter((f) => {
      if (!filters.severities.has(f.severity)) return false
      if (filters.owasp && f.owasp_category !== filters.owasp) return false
      if (filters.fileSearch && !f.file.toLowerCase().includes(filters.fileSearch.toLowerCase())) return false
      return true
    })
  }, [findings, filters])

  const grouped = useMemo(() => {
    const g: Record<string, SecurityFinding[]> = { critical: [], major: [], minor: [] }
    for (const f of filtered) {
      if (f.severity in g) g[f.severity].push(f)
    }
    return g
  }, [filtered])

  const total = findings.length
  const shown = filtered.length

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Results toolbar */}
      <div className="flex h-10 flex-shrink-0 items-center gap-2 border-b border-border-default px-3">
        <button
          onClick={onReset}
          title="New scan"
          className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
        <span className="text-[10px] text-fg-subtle font-mono truncate max-w-[160px]" title={source}>
          {source.split('/').pop() ?? source}
        </span>
        <div className="flex flex-1 items-center gap-1.5">
          <SeverityBadges counts={severityCounts} />
        </div>
        {total === 0 && (
          <span className="text-xs text-success-fg font-medium">No findings</span>
        )}
        {total > 0 && shown < total && (
          <span className="text-[10px] text-fg-subtle">{shown}/{total} shown</span>
        )}
        <button
          onClick={() => setShowReport((v) => !v)}
          className="text-[10px] text-fg-muted hover:text-fg-default"
        >
          {showReport ? 'Hide report' : 'Full report'}
        </button>
      </div>

      {/* Filter bar */}
      {findings.length > 0 && (
        <FilterBar findings={findings} filters={filters} onChange={setFilters} />
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {total === 0 && (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <Shield className="h-8 w-8 text-success-fg opacity-60" />
            <p className="text-sm font-medium text-fg-default">No security issues found</p>
            <p className="text-xs text-fg-subtle">
              Scanned with: {toolsUsed.join(', ')}
            </p>
          </div>
        )}

        {showReport ? (
          <pre className="whitespace-pre-wrap font-mono text-[11px] text-fg-default leading-relaxed">
            {report}
          </pre>
        ) : (
          SEV_ORDER.map((sev) => (
            <FindingsGroup
              key={sev}
              severity={sev}
              findings={grouped[sev] ?? []}
              repoId={repoId}
            />
          ))
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Scan history
// ---------------------------------------------------------------------------

function ScanHistory({
  repoId,
  onLoad,
}: {
  repoId: string
  onLoad: (report: SecurityReport) => void
}) {
  const [scans, setScans] = useState<SecurityScanMeta[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(() => {
    setLoading(true)
    api.listSecurityScans(repoId).then((r) => {
      setScans(r.scans)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [repoId])

  useEffect(() => { refresh() }, [refresh])

  async function handleLoad(jobId: string) {
    try {
      const report = await api.getSecurityScan(repoId, jobId)
      onLoad(report)
    } catch {
      toast.error('Could not load scan report')
    }
  }

  async function handleDelete(jobId: string) {
    try {
      await api.deleteSecurityScan(repoId, jobId)
      setScans((prev) => prev.filter((s) => s.job_id !== jobId))
      toast.success('Scan deleted')
    } catch {
      toast.error('Delete failed')
    }
  }

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-xs text-fg-subtle">Loading history…</p>
      </div>
    )
  }

  if (scans.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center py-12">
        <AlertTriangle className="h-8 w-8 text-fg-subtle opacity-40" />
        <p className="text-sm text-fg-muted">No saved scans yet</p>
        <p className="text-xs text-fg-subtle">Run a scan and its report will appear here.</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-2">
      {scans.map((scan) => (
        <div
          key={scan.job_id}
          className="flex items-center gap-3 rounded-lg border border-border-default bg-canvas-default px-3 py-2"
        >
          <Shield className="h-4 w-4 flex-shrink-0 text-fg-subtle" />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="truncate font-mono text-[11px] text-fg-default" title={scan.source}>
              {scan.source.split('/').pop() ?? scan.source}
            </span>
            <span className="text-[10px] text-fg-subtle">
              {new Date(scan.created_at).toLocaleString()}
            </span>
          </div>
          <SeverityBadges counts={scan.severity_counts} />
          {Object.values(scan.severity_counts).every((n) => n === 0) && (
            <span className="text-[10px] text-success-fg font-medium">Clean</span>
          )}
          <button
            onClick={() => void handleLoad(scan.job_id)}
            className="rounded px-2 py-1 text-[10px] font-medium text-accent-fg hover:bg-accent-subtle"
          >
            View
          </button>
          <button
            onClick={() => void handleDelete(scan.job_id)}
            title="Delete scan"
            className="rounded p-1 text-fg-subtle hover:bg-danger-subtle hover:text-danger-fg"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Empty / idle state
// ---------------------------------------------------------------------------

function IdleEmpty({
  repoId,
  onScan,
}: {
  repoId: string
  onScan: (source: string, token: string, config: string, llm: boolean) => void
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center">
      <ScanForm repoId={repoId} onSubmit={onScan} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main SecurityPanel
// ---------------------------------------------------------------------------

type PanelTab = 'scan' | 'history'

export function SecurityPanel({ repoId }: { repoId: string }) {
  const [activeTab, setActiveTab] = useState<PanelTab>('scan')
  const [returnTab, setReturnTab] = useState<PanelTab>('scan')
  const { state, scan, reset, loadSaved, dismissOverride } = useSecurityScan(repoId)

  function handleScan(source: string, token: string, config: string, llm: boolean) {
    void scan({ source, token: token || undefined, semgrep_config: config, run_llm_triage: llm })
  }

  function handleReset() {
    reset()
    setActiveTab(returnTab)
    setReturnTab('scan')
  }

  function handleLoadSaved(report: SecurityReport) {
    setReturnTab('history')
    loadSaved(report)
    setActiveTab('scan')
  }

  // When a scan starts from the scan tab, switch to scan tab
  useEffect(() => {
    if (state.phase === 'polling' || state.phase === 'submitting') {
      setActiveTab('scan')
    }
  }, [state.phase])

  // Header badges
  const headerCounts: Record<string, number> = state.phase === 'done'
    ? state.severityCounts
    : state.phase === 'polling'
      ? state.severityCounts
      : {}

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex h-10 flex-shrink-0 items-center border-b border-border-default px-4 gap-0">
        {(['scan', 'history'] as PanelTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => {
              if (state.phase === 'done' || state.phase === 'idle' || state.phase === 'error') {
                if (tab === 'scan' && state.phase === 'done') dismissOverride()
                setActiveTab(tab)
              } else {
                setActiveTab(tab)
              }
            }}
            className={cn(
              'px-3 py-1.5 text-xs font-medium transition-colors capitalize',
              activeTab === tab
                ? 'border-b-2 border-accent-emphasis text-accent-fg'
                : 'text-fg-muted hover:text-fg-default',
            )}
          >
            {tab === 'scan' ? 'Scan' : 'History'}
          </button>
        ))}
        {/* Severity badge counters in header */}
        {Object.keys(headerCounts).length > 0 && (
          <span className="ml-3">
            <SeverityBadges counts={headerCounts} />
          </span>
        )}
      </div>

      {/* Content */}
      {activeTab === 'scan' && (
        <>
          {state.phase === 'idle' && (
            <IdleEmpty repoId={repoId} onScan={handleScan} />
          )}
          {state.phase === 'submitting' && (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-xs text-fg-subtle">Submitting scan…</p>
            </div>
          )}
          {state.phase === 'polling' && (
            <div className="flex flex-1 items-center justify-center">
              <ScanProgress
                completed={state.completed}
                total={state.total}
                currentPhase={state.currentPhase}
                startedAt={state.startedAt}
                onCancel={handleReset}
              />
            </div>
          )}
          {state.phase === 'done' && (
            <ScanResults
              repoId={repoId}
              source={state.source}
              findings={state.findings}
              report={state.report}
              severityCounts={state.severityCounts}
              toolsUsed={state.toolsUsed}
              onReset={handleReset}
            />
          )}
          {state.phase === 'error' && (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 py-12">
              <AlertTriangle className="h-8 w-8 text-danger-fg opacity-60" />
              <p className="text-sm font-medium text-fg-default">Scan failed</p>
              <p className="max-w-xs text-center text-xs text-fg-subtle">{state.message}</p>
              <button
                onClick={handleReset}
                className="mt-2 flex items-center gap-1.5 rounded-md border border-border-default px-3 py-1.5 text-xs text-fg-default hover:bg-canvas-subtle"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Try again
              </button>
            </div>
          )}
        </>
      )}

      {activeTab === 'history' && (
        <ScanHistory repoId={repoId} onLoad={handleLoadSaved} />
      )}
    </div>
  )
}
