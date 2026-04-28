import { useState, useEffect, useRef } from 'react'
import {
  FolderGit2,
  Plus,
  Trash2,
  RefreshCw,
  RotateCcw,
  Sun,
  Moon,
//  Telescope,
  ChevronRight,
  MessageSquare,
  PenLine,
  Loader2,
  LogOut,
  User,
  Shield,
} from 'lucide-react'
import { toast } from 'sonner'
import { useRepoList, useDeleteRepo, useResyncRepo } from '@/hooks/useRepos'
import { useSessionList, useCreateSession, useDeleteSession } from '@/hooks/useSessions'
import { useAppStore } from '@/store/app'
import { api } from '@/lib/api'
import { RepoConnectDialog } from './RepoConnectDialog'
import { cn } from '@/lib/utils'
import logo from '@/assets/images/aquila-text.svg'

// ---------------------------------------------------------------------------
// Delete repo confirmation dialog
// ---------------------------------------------------------------------------

function DeleteRepoDialog({
  repoId,
  onConfirm,
  onCancel,
}: {
  repoId: string
  onConfirm: (opts: { deleteSessions: boolean; deleteDocs: boolean }) => void
  onCancel: () => void
}) {
  const [deleteSessions, setDeleteSessions] = useState(false)
  const [deleteDocs, setDeleteDocs] = useState(false)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onCancel}
    >
      <div
        className="w-80 rounded-lg border border-border-default bg-canvas-overlay p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-1 text-sm font-semibold text-fg-default">Delete repository</h3>
        <p className="mb-4 text-xs text-fg-muted">
          Permanently remove all graph nodes and vector chunks for{' '}
          <span className="font-mono font-medium text-fg-default">{repoId}</span>.
          This cannot be undone.
        </p>

        <div className="mb-5 space-y-2">
          <label className="flex cursor-pointer items-center gap-2.5">
            <input
              type="checkbox"
              checked={deleteSessions}
              onChange={(e) => setDeleteSessions(e.target.checked)}
              className="h-3.5 w-3.5 accent-danger-fg"
            />
            <span className="text-xs text-fg-default">Also delete conversations</span>
          </label>
          <label className="flex cursor-pointer items-center gap-2.5">
            <input
              type="checkbox"
              checked={deleteDocs}
              onChange={(e) => setDeleteDocs(e.target.checked)}
              className="h-3.5 w-3.5 accent-danger-fg"
            />
            <span className="text-xs text-fg-default">Also delete documentation</span>
          </label>
        </div>

        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md border border-border-default px-3 py-1.5 text-xs text-fg-muted hover:bg-canvas-subtle"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm({ deleteSessions, deleteDocs })}
            className="rounded-md bg-danger-emphasis px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Session list for the active repo
// ---------------------------------------------------------------------------

function SessionList({ repoId }: { repoId: string }) {
  // Still fetch so server sessions are synced into the local store.
  const { isLoading }   = useSessionList(repoId)
  const createSession   = useCreateSession(repoId)
  const deleteSession   = useDeleteSession(repoId)

  const activeSessionId = useAppStore((s) => s.activeSessions[repoId])
  const setActiveSession = useAppStore((s) => s.setActiveSession)

  // Read from the persisted local store — sessions survive server restarts.
  const allSessions = useAppStore((s) => s.sessions)
  const sessions = Object.values(allSessions)
    .filter((s) => s.repo_id === repoId)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

  async function handleNew() {
    try {
      await createSession.mutateAsync('New Chat')
    } catch {
      toast.error('Failed to create conversation')
    }
  }

  async function handleDelete(e: React.MouseEvent, sessionId: string) {
    e.stopPropagation()
    try {
      await deleteSession.mutateAsync(sessionId)
      toast.success('Conversation deleted')
    } catch {
      toast.error('Failed to delete conversation')
    }
  }

  return (
    <div className="mt-3">
      {/* Header */}
      <div className="mb-1 flex items-center justify-between px-2">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-fg-subtle">
          Conversations
        </p>
        <button
          onClick={() => void handleNew()}
          disabled={createSession.isPending}
          title="New conversation"
          className="rounded p-0.5 text-fg-subtle transition-colors hover:bg-canvas-subtle hover:text-fg-default disabled:opacity-40"
        >
          <PenLine className="h-3 w-3" />
        </button>
      </div>

      {isLoading ? (
        <div className="space-y-1 px-1">
          {[1, 2].map((i) => (
            <div key={i} className="h-7 animate-pulse rounded-md bg-canvas-subtle" />
          ))}
        </div>
      ) : sessions.length === 0 ? (
        <button
          onClick={() => void handleNew()}
          disabled={createSession.isPending}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-fg-subtle transition-colors hover:bg-canvas-subtle hover:text-fg-default disabled:opacity-40"
        >
          <Plus className="h-3 w-3" />
          Start a conversation
        </button>
      ) : (
        <ul className="space-y-0.5">
          {sessions.map((session) => {
            const isActive = session.session_id === activeSessionId
            return (
              <li key={session.session_id}>
                <button
                  onClick={() => setActiveSession(repoId, session.session_id)}
                  className={cn(
                    'group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors',
                    isActive
                      ? 'border-l-2 border-accent-emphasis bg-accent-subtle pl-1.5 font-medium text-accent-fg'
                      : 'text-fg-muted hover:bg-canvas-subtle hover:text-fg-default',
                  )}
                >
                  <MessageSquare className="h-3 w-3 flex-shrink-0 opacity-60" />
                  <span className="flex-1 truncate text-left" title={session.title}>
                    {session.title}
                  </span>
                  {session.message_count > 0 && (
                    <span className="flex-shrink-0 text-[10px] text-fg-subtle opacity-60 group-hover:opacity-100">
                      {session.message_count}
                    </span>
                  )}
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => void handleDelete(e, session.session_id)}
                    onKeyDown={(e) =>
                      e.key === 'Enter' &&
                      void handleDelete(e as unknown as React.MouseEvent, session.session_id)
                    }
                    className="hidden rounded p-0.5 text-danger-fg transition-colors hover:bg-canvas-default group-hover:block"
                    title="Delete conversation"
                  >
                    <Trash2 className="h-3 w-3" />
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Single repo row with resync support
// ---------------------------------------------------------------------------

function RepoItem({
  repo,
  isActive,
  onSelect,
  onDeleteClick,
}: {
  repo: string
  isActive: boolean
  onSelect: () => void
  onDeleteClick: (e: React.MouseEvent) => void
}) {
  const repoSource   = useAppStore((s) => s.repoSources[repo])
  const setRepoSource = useAppStore((s) => s.setRepoSource)
  const { phase, result, start, reset } = useResyncRepo(repo)
  const isRunning = phase === 'running'

  // Show sync button only for sources the server can actually resync.
  // 'local' needs an absolute path — browser zip-uploads store just a folder name.
  const resyncAvailable = !!repoSource && (
    repoSource.source_type !== 'local' ||
    repoSource.path.startsWith('/') ||
    /^[A-Za-z]:[/\\]/.test(repoSource.path)
  )

  // Prompt immediately only when we know a token was required at ingest time.
  // For old/unknown repos we attempt the resync first and prompt on auth failure.
  const isRemote = repoSource?.source_type !== 'local'
  const needsToken = resyncAvailable && !!repoSource?.has_token && !repoSource.github_token
  const [tokenPromptOpen, setTokenPromptOpen] = useState(false)
  const [tokenInput, setTokenInput] = useState('')

  // Toast on completion
  useEffect(() => {
    if (phase === 'done' && result) {
      const changed = result.changed_files ?? 0
      if (changed === 0) {
        toast.success(`"${repo}" is already up to date`)
      } else {
        toast.success(`"${repo}" resynced — ${changed} file${changed !== 1 ? 's' : ''} updated`)
      }
      reset()
    } else if (phase === 'error' && result) {
      const msg = result.error ?? 'unknown error'
      const isAuthError = isRemote && /401|403|unauthorized|forbidden|authentication|rate.?limit|token/i.test(msg)
      if (isAuthError) {
        setTokenPromptOpen(true)
      } else {
        toast.error(`Resync failed: ${msg}`)
      }
      reset()
    }
  }, [phase, result, repo, reset])

  async function handleResync(e: React.MouseEvent) {
    e.stopPropagation()
    if (!repoSource || isRunning) return
    if (needsToken) {
      setTokenPromptOpen(true)
      return
    }
    await start(repoSource)
  }

  async function handleTokenSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!repoSource) return
    const tok = tokenInput.trim() || undefined
    // Clearing the token marks the repo as public — has_token gets corrected in the graph on resync.
    const updated = { ...repoSource, github_token: tok, has_token: !!tok }
    setRepoSource(repo, updated)
    setTokenPromptOpen(false)
    setTokenInput('')
    await start(updated)
  }

  const canResync = !!repoSource && !isRunning

  return (
    <>
    <button
      onClick={onSelect}
      className={cn(
        'group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors',
        isActive
          ? 'border-l-2 border-accent-emphasis bg-accent-subtle pl-1.5 font-medium text-accent-fg'
          : 'text-fg-muted hover:bg-canvas-subtle hover:text-fg-default',
      )}
    >
      <FolderGit2 className="h-3.5 w-3.5 flex-shrink-0" />
      <span className="flex-1 truncate text-left">{repo}</span>

      {/* Resync button — only shown when source is git-tracked */}
      {resyncAvailable && (
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => void handleResync(e)}
          onKeyDown={(e) => e.key === 'Enter' && void handleResync(e as unknown as React.MouseEvent)}
          title={isRunning ? 'Resyncing…' : needsToken ? 'Token required — click to provide' : 'Resync embeddings from latest commits'}
          className={cn(
            'hidden rounded p-0.5 transition-colors group-hover:block',
            canResync
              ? 'text-fg-subtle hover:bg-canvas-default hover:text-accent-fg'
              : 'cursor-not-allowed text-fg-subtle opacity-50',
          )}
        >
          {isRunning
            ? <Loader2 className="h-3 w-3 animate-spin" />
            : <RotateCcw className="h-3 w-3" />
          }
        </span>
      )}

      <span
        role="button"
        tabIndex={0}
        onClick={onDeleteClick}
        onKeyDown={(e) =>
          e.key === 'Enter' && onDeleteClick(e as unknown as React.MouseEvent)
        }
        className="hidden rounded p-0.5 text-danger-fg transition-colors hover:bg-canvas-default group-hover:block"
        title="Delete repo"
      >
        <Trash2 className="h-3 w-3" />
      </span>

      {isActive && <ChevronRight className="h-3 w-3 flex-shrink-0" />}
    </button>

    {/* Token prompt modal for private repos after logout */}
    {tokenPromptOpen && (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
        onClick={() => setTokenPromptOpen(false)}
      >
        <form
          className="w-80 rounded-lg border border-border-default bg-canvas-overlay p-5 shadow-xl"
          onClick={(e) => e.stopPropagation()}
          onSubmit={(e) => void handleTokenSubmit(e)}
        >
          <p className="mb-1 text-sm font-medium text-fg-default">Access token required</p>
          <p className="mb-3 text-xs text-fg-muted">
            This repo was ingested with a token. Re-enter it to resync <strong>{repo}</strong>.
          </p>
          <input
            autoFocus
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="ghp_… / glpat-… / token"
            className="mb-3 w-full rounded border border-border-default bg-canvas-inset px-3 py-1.5 text-xs text-fg-default placeholder:text-fg-subtle focus:outline-none focus:ring-1 focus:ring-accent-emphasis"
          />
          <p className="mb-3 text-[11px] text-fg-subtle">
            Public repo?{' '}
            <button
              type="submit"
              className="underline underline-offset-2 hover:text-fg-default"
            >
              Resync without token
            </button>
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setTokenPromptOpen(false)}
              className="rounded px-3 py-1.5 text-xs text-fg-muted hover:bg-canvas-subtle"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!tokenInput.trim()}
              className="rounded bg-accent-emphasis px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
            >
              Resync
            </button>
          </div>
        </form>
      </div>
    )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Main sidebar
// ---------------------------------------------------------------------------

export function Sidebar({ onAdminOpen }: { onAdminOpen?: () => void }) {
  const [connectOpen, setConnectOpen] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)

  const { data, isLoading, refetch } = useRepoList()
  const deleteRepo                   = useDeleteRepo()

  const activeRepoId      = useAppStore((s) => s.activeRepoId)
  const setActiveRepo     = useAppStore((s) => s.setActiveRepoId)
  const setRepoSource     = useAppStore((s) => s.setRepoSource)

  // If the persisted activeRepoId is not in the accessible repo list (e.g. after
  // a user switch or membership change), clear it so we don't show inaccessible data.
  useEffect(() => {
    if (!isLoading && data && activeRepoId && !data.repos.includes(activeRepoId)) {
      setActiveRepo(null)
    }
  }, [data, isLoading, activeRepoId, setActiveRepo])

  // Re-hydrate repoSources from the backend on first load so the sync button
  // always reflects the real source type, even after logout (which clears the
  // store) or when the dialog stored a stale 'local' entry for a zip upload.
  const hydratedRef = useRef(false)
  useEffect(() => {
    if (!data?.repos || hydratedRef.current) return
    hydratedRef.current = true
    for (const repoId of data.repos) {
      api.getRepoSource(repoId)
        .then((src) => {
          // Zip-uploaded repos can't be resynced — omit them from the store
          // so the sync button stays hidden.
          if (src.source_type === 'zip') return
          setRepoSource(repoId, {
            path: src.path,
            source_type: src.source_type as 'local' | 'github' | 'gitlab' | 'gitea' | 'git',
            has_token: src.has_token,
          })
        })
        .catch(() => { /* no job record (CLI-ingested or zip) — sync button stays hidden */ })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.repos])
  const theme             = useAppStore((s) => s.theme)
  const toggleTheme       = useAppStore((s) => s.toggleTheme)
  const authUser          = useAppStore((s) => s.authUser)
  const authDisabled      = useAppStore((s) => s.authDisabled)
  const authRefreshToken  = useAppStore((s) => s.authRefreshToken)
  const clearAuth         = useAppStore((s) => s.clearAuth)

  async function handleLogout() {
    try {
      if (authRefreshToken) await api.logout(authRefreshToken)
    } catch { /* best-effort */ }
    clearAuth()
  }

  const repos = data?.repos ?? []

  function handleDeleteClick(e: React.MouseEvent, repoId: string) {
    e.stopPropagation()
    setPendingDelete(repoId)
  }

  async function handleDeleteConfirm(opts: { deleteSessions: boolean; deleteDocs: boolean }) {
    if (!pendingDelete) return
    const repoId = pendingDelete
    setPendingDelete(null)
    try {
      await deleteRepo.mutateAsync({ repoId, ...opts })
      if (activeRepoId === repoId) setActiveRepo(null)
      toast.success(`Deleted "${repoId}"`)
    } catch {
      toast.error('Delete failed')
    }
  }

  return (
    <aside className="flex w-56 flex-shrink-0 flex-col border-r border-border-default bg-canvas-overlay">
      {/* Brand */}
      <div className="flex h-12 items-center gap-2 border-b border-border-default px-3">
        {/* <Telescope className="h-4 w-4 flex-shrink-0 text-accent-fg" /> */}
        <img src={logo} alt="Aquila Atlas" className="h-12" />
        
        <span className="flex-1 text-sm font-semibold tracking-tight text-fg-default">
          Aquila Atlas
        </span>

        <button
          onClick={() => void refetch()}
          title="Refresh"
          className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Scrollable nav area */}
      <nav className="flex-1 overflow-y-auto p-2">
        {/* Repositories */}
        <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-widest text-fg-subtle">
          Repositories
        </p>

        {isLoading ? (
          <div className="space-y-1 px-1 pt-1">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-7 animate-pulse rounded-md bg-canvas-subtle" />
            ))}
          </div>
        ) : repos.length === 0 ? (
          <p className="px-2 py-4 text-center text-xs text-fg-subtle">No repos yet</p>
        ) : (
          <ul className="space-y-0.5">
            {repos.map((repo) => (
              <li key={repo}>
                <RepoItem
                  repo={repo}
                  isActive={activeRepoId === repo}
                  onSelect={() => setActiveRepo(repo)}
                  onDeleteClick={(e) => handleDeleteClick(e, repo)}
                />
              </li>
            ))}
          </ul>
        )}

        {/* Session list appears when a repo is active */}
        {activeRepoId && <SessionList repoId={activeRepoId} />}
      </nav>

      {/* Footer actions */}
      <div className="border-t border-border-default p-2 space-y-0.5">
        <button
          onClick={() => setConnectOpen(true)}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-fg-muted transition-colors hover:bg-canvas-subtle hover:text-fg-default"
        >
          <Plus className="h-3.5 w-3.5" />
          Connect repository
        </button>
        <button
          onClick={toggleTheme}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-fg-muted transition-colors hover:bg-canvas-subtle hover:text-fg-default"
        >
          {theme === 'dark' ? (
            <Sun className="h-3.5 w-3.5" />
          ) : (
            <Moon className="h-3.5 w-3.5" />
          )}
          {theme === 'dark' ? 'Light mode' : 'Dark mode'}
        </button>

        {!authDisabled && authUser && (
          <div className="mt-1 border-t border-border-default pt-1.5">
            {authUser.role === 'admin' && (
              <button
                onClick={onAdminOpen}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-fg-muted transition-colors hover:bg-canvas-subtle hover:text-fg-default"
              >
                <Shield className="h-3.5 w-3.5 text-accent-fg" />
                Admin panel
              </button>
            )}
            <div className="flex items-center gap-2 px-2 py-1">
              <User className="h-3.5 w-3.5 flex-shrink-0 text-fg-subtle" />
              <span className="flex-1 truncate text-xs text-fg-muted" title={authUser.email}>
                {authUser.display_name || authUser.email}
              </span>
              <button
                onClick={() => void handleLogout()}
                title="Sign out"
                className="rounded p-0.5 text-fg-subtle hover:bg-canvas-subtle hover:text-danger-fg"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>

      <RepoConnectDialog open={connectOpen} onOpenChange={setConnectOpen} />

      {pendingDelete && (
        <DeleteRepoDialog
          repoId={pendingDelete}
          onConfirm={(opts) => void handleDeleteConfirm(opts)}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </aside>
  )
}
