import { useState } from 'react'
import { Telescope, GitBranch, Search, MessageSquare } from 'lucide-react'
import { RepoConnectDialog } from './RepoConnectDialog'

const FEATURES = [
  { icon: GitBranch,     label: 'Dependency graph',   desc: 'Understand how components connect' },
  { icon: Search,        label: 'Hybrid search',       desc: 'Dense + sparse semantic code search' },
  { icon: MessageSquare, label: 'AI-powered Q&A',      desc: 'Multi-turn chat with source citations' },
]

export function EmptyState() {
  const [open, setOpen] = useState(false)

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-8 p-8 text-center">
      {/* Logo */}
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-accent-fg/20 bg-accent-subtle">
        <Telescope className="h-8 w-8 text-accent-fg" />
      </div>

      {/* Title */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-fg-default">Aquila-Atlas</h1>
        <p className="mt-2 max-w-sm text-sm text-fg-muted">
          The atlas of your codebase. Ingest a repository and explore it with
          natural language search and AI Q&amp;A.
        </p>
      </div>

      {/* Feature list */}
      <div className="flex gap-4">
        {FEATURES.map(({ icon: Icon, label, desc }) => (
          <div
            key={label}
            className="flex w-36 flex-col items-center gap-2 rounded-xl border border-border-default bg-canvas-overlay p-3 text-center"
          >
            <Icon className="h-5 w-5 text-accent-fg" />
            <p className="text-xs font-medium text-fg-default">{label}</p>
            <p className="text-[10px] text-fg-subtle">{desc}</p>
          </div>
        ))}
      </div>

      {/* CTA */}
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-lg bg-accent-emphasis px-5 py-2.5 text-sm font-medium text-fg-onEmphasis shadow-lg shadow-accent-emphasis/20 hover:opacity-90 transition-opacity"
      >
        Connect a repository
      </button>

      <RepoConnectDialog open={open} onOpenChange={setOpen} />
    </div>
  )
}
