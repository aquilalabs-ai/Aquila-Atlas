import { useState, type ReactNode } from 'react'
import {
  X,
  Users,
  Database,
  Server,
  RefreshCw,
  Trash2,
  Shield,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  UserX,
  UserCheck,
} from 'lucide-react'
import { toast } from 'sonner'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type UserInfo, type RepoAdminInfo, type SystemStatsResponse, type PurgeResult } from '@/lib/api'
import { cn } from '@/lib/utils'

type AdminTab = 'users' | 'repos' | 'system'

// ---------------------------------------------------------------------------
// Confirm dialog
// ---------------------------------------------------------------------------

function ConfirmDialog({
  title,
  message,
  confirmLabel = 'Confirm',
  danger = true,
  onConfirm,
  onCancel,
}: {
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60" onClick={onCancel}>
      <div
        className="w-80 rounded-lg border border-border-default bg-canvas-overlay p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-1 text-sm font-semibold text-fg-default">{title}</h3>
        <p className="mb-5 text-xs text-fg-muted">{message}</p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md border border-border-default px-3 py-1.5 text-xs text-fg-muted hover:bg-canvas-subtle"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={cn(
              'rounded-md px-3 py-1.5 text-xs font-medium text-white hover:opacity-90',
              danger ? 'bg-danger-emphasis' : 'bg-accent-emphasis',
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Users tab
// ---------------------------------------------------------------------------

function UsersTab() {
  const qc = useQueryClient()
  const { data: license } = useQuery({ queryKey: ['admin', 'license'], queryFn: api.adminGetLicense })
  const { data: users, isLoading, refetch } = useQuery({ queryKey: ['admin', 'users'], queryFn: api.adminListUsers })
  const [confirm, setConfirm] = useState<{ type: 'delete' | 'deactivate' | 'activate' | 'role'; user: UserInfo; role?: string } | null>(null)

  const updateUser = useMutation({
    mutationFn: ({ userId, body }: { userId: string; body: Parameters<typeof api.adminUpdateUser>[1] }) =>
      api.adminUpdateUser(userId, body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['admin', 'users'] }); void qc.invalidateQueries({ queryKey: ['admin', 'license'] }) },
  })

  const deleteUser = useMutation({
    mutationFn: (userId: string) => api.adminDeleteUser(userId),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['admin', 'users'] }); void qc.invalidateQueries({ queryKey: ['admin', 'license'] }) },
  })

  async function handleConfirm() {
    if (!confirm) return
    try {
      if (confirm.type === 'delete') {
        await deleteUser.mutateAsync(confirm.user.user_id)
        toast.success(`Deleted ${confirm.user.email}`)
      } else if (confirm.type === 'deactivate') {
        await updateUser.mutateAsync({ userId: confirm.user.user_id, body: { is_active: false } })
        toast.success(`Deactivated ${confirm.user.email}`)
      } else if (confirm.type === 'activate') {
        await updateUser.mutateAsync({ userId: confirm.user.user_id, body: { is_active: true } })
        toast.success(`Activated ${confirm.user.email}`)
      } else if (confirm.type === 'role' && confirm.role) {
        await updateUser.mutateAsync({ userId: confirm.user.user_id, body: { role: confirm.role } })
        toast.success(`Changed ${confirm.user.email} to ${confirm.role}`)
      }
    } catch (e) {
      toast.error((e as Error).message)
    }
    setConfirm(null)
  }

  return (
    <div className="flex flex-col gap-4">
      {/* License bar */}
      {license && (
        <div className="rounded-lg border border-border-default bg-canvas-subtle p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-fg-default">
              {license.customer_name || 'Instance'} License
            </span>
            <span className={cn('text-xs font-medium', license.valid ? 'text-success-fg' : 'text-danger-fg')}>
              {license.valid ? 'Valid' : 'Expired'}
            </span>
          </div>
          {license.customer_id && (
            <div className="mb-2 text-xs text-fg-muted">
              Organization ID: <span className="font-mono text-fg-default">{license.customer_id}</span>
            </div>
          )}
          <div className="mb-1 flex items-center justify-between text-xs text-fg-muted">
            <span>{license.seats_used} / {license.max_seats} seats used</span>
            {license.expires_at && <span>Expires {new Date(license.expires_at).toLocaleDateString()}</span>}
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-canvas-default">
            <div
              className={cn('h-full rounded-full', license.seats_used >= license.max_seats ? 'bg-danger-emphasis' : 'bg-accent-emphasis')}
              style={{ width: `${Math.min(100, (license.seats_used / Math.max(license.max_seats, 1)) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Users table */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-fg-subtle">Users</span>
        <button onClick={() => void refetch()} className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-fg-muted" />
        </div>
      ) : !users?.length ? (
        <p className="py-6 text-center text-xs text-fg-subtle">No users</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border-default">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-default bg-canvas-subtle">
                <th className="px-3 py-2 text-left font-medium text-fg-muted">User</th>
                <th className="px-3 py-2 text-left font-medium text-fg-muted">Role</th>
                <th className="px-3 py-2 text-left font-medium text-fg-muted">Auth</th>
                <th className="px-3 py-2 text-left font-medium text-fg-muted">Status</th>
                <th className="px-3 py-2 text-right font-medium text-fg-muted">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-default">
              {users.map((u) => (
                <tr key={u.user_id} className="hover:bg-canvas-subtle">
                  <td className="px-3 py-2">
                    <div className="font-medium text-fg-default">{u.display_name || u.email}</div>
                    {u.display_name && <div className="text-fg-subtle">{u.email}</div>}
                  </td>
                  <td className="px-3 py-2">
                    <span className={cn(
                      'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium',
                      u.role === 'admin'
                        ? 'bg-accent-subtle text-accent-fg'
                        : 'bg-canvas-subtle text-fg-muted',
                    )}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-fg-muted">{u.auth_mode}</td>
                  <td className="px-3 py-2">
                    {u.is_active
                      ? <CheckCircle2 className="h-3.5 w-3.5 text-success-fg" />
                      : <XCircle className="h-3.5 w-3.5 text-danger-fg" />
                    }
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-1">
                      {/* Toggle role */}
                      <button
                        onClick={() => setConfirm({ type: 'role', user: u, role: u.role === 'admin' ? 'user' : 'admin' })}
                        title={u.role === 'admin' ? 'Demote to user' : 'Promote to admin'}
                        className="rounded p-1 text-fg-subtle hover:bg-canvas-default hover:text-accent-fg"
                      >
                        <Shield className="h-3.5 w-3.5" />
                      </button>
                      {/* Toggle active */}
                      <button
                        onClick={() => setConfirm({ type: u.is_active ? 'deactivate' : 'activate', user: u })}
                        title={u.is_active ? 'Deactivate' : 'Activate'}
                        className="rounded p-1 text-fg-subtle hover:bg-canvas-default hover:text-fg-default"
                      >
                        {u.is_active ? <UserX className="h-3.5 w-3.5" /> : <UserCheck className="h-3.5 w-3.5" />}
                      </button>
                      {/* Delete */}
                      <button
                        onClick={() => setConfirm({ type: 'delete', user: u })}
                        title="Delete user"
                        className="rounded p-1 text-fg-subtle hover:bg-canvas-default hover:text-danger-fg"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {confirm && (
        <ConfirmDialog
          title={
            confirm.type === 'delete' ? 'Delete user' :
            confirm.type === 'deactivate' ? 'Deactivate user' :
            confirm.type === 'activate' ? 'Activate user' :
            confirm.role === 'admin' ? 'Promote to admin' : 'Demote to user'
          }
          message={
            confirm.type === 'delete'
              ? `Permanently delete ${confirm.user.email}? Their seat will be freed.`
              : confirm.type === 'deactivate'
              ? `Deactivate ${confirm.user.email}? Their active sessions will be revoked.`
              : confirm.type === 'activate'
              ? `Re-activate ${confirm.user.email}?`
              : `Change ${confirm.user.email}'s role to ${confirm.role}?`
          }
          confirmLabel={confirm.type === 'delete' ? 'Delete' : 'Confirm'}
          danger={confirm.type === 'delete' || confirm.type === 'deactivate'}
          onConfirm={() => void handleConfirm()}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Repos tab
// ---------------------------------------------------------------------------

function ReposTab() {
  const qc = useQueryClient()
  const { data: repos, isLoading, refetch } = useQuery({ queryKey: ['admin', 'repos'], queryFn: api.adminListRepos })
  const [expanded, setExpanded] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<RepoAdminInfo | null>(null)

  const deleteRepo = useMutation({
    mutationFn: (repoId: string) => api.adminDeleteRepo(repoId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'repos'] }),
  })

  async function handleDelete(repo: RepoAdminInfo) {
    try {
      const res = await deleteRepo.mutateAsync(repo.repo_id)
      toast.success(`Deleted "${repo.repo_id}" — ${res.graph_nodes_deleted} nodes, ${res.vector_chunks_deleted} chunks removed`)
    } catch (e) {
      toast.error((e as Error).message)
    }
    setConfirm(null)
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-fg-subtle">Ingested Repositories</span>
        <button onClick={() => void refetch()} className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-fg-muted" />
        </div>
      ) : !repos?.length ? (
        <p className="py-6 text-center text-xs text-fg-subtle">No repos ingested</p>
      ) : (
        <div className="space-y-1">
          {repos.map((repo) => {
            const isOpen = expanded === repo.repo_id
            return (
              <div key={repo.repo_id} className="overflow-hidden rounded-lg border border-border-default">
                <button
                  onClick={() => setExpanded(isOpen ? null : repo.repo_id)}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-xs hover:bg-canvas-subtle"
                >
                  {isOpen ? <ChevronDown className="h-3.5 w-3.5 flex-shrink-0 text-fg-subtle" /> : <ChevronRight className="h-3.5 w-3.5 flex-shrink-0 text-fg-subtle" />}
                  <span className="flex-1 truncate text-left font-medium text-fg-default">{repo.repo_id}</span>
                  <span className="text-fg-subtle">{repo.vector_chunks.toLocaleString()} chunks</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); setConfirm(repo) }}
                    title="Delete repo (Neo4j + Qdrant)"
                    className="ml-2 rounded p-1 text-fg-subtle hover:bg-canvas-default hover:text-danger-fg"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </button>

                {isOpen && (
                  <div className="border-t border-border-default bg-canvas-subtle px-4 py-3">
                    <div className="grid grid-cols-2 gap-x-8 gap-y-1.5 text-xs sm:grid-cols-3">
                      <Stat label="Graph nodes" value={repo.graph_nodes.toLocaleString()} />
                      <Stat label="Relationships" value={repo.graph_relationships.toLocaleString()} />
                      <Stat label="Vector chunks" value={repo.vector_chunks.toLocaleString()} />
                      <Stat label="Files" value={repo.files.toLocaleString()} />
                      {repo.commit_sha && (
                        <Stat label="Commit" value={repo.commit_sha.slice(0, 8)} mono />
                      )}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {confirm && (
        <ConfirmDialog
          title="Delete repository"
          message={`Permanently delete "${confirm.repo_id}" from Neo4j and Qdrant? All conversations and documentation for this repo will also be removed. This cannot be undone.`}
          confirmLabel="Delete"
          onConfirm={() => void handleDelete(confirm)}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  )
}

function Stat({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <span className="text-fg-subtle">{label}: </span>
      <span className={cn('font-medium text-fg-default', mono && 'font-mono')}>{value}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// System tab
// ---------------------------------------------------------------------------

function SystemTab() {
  const { data: stats, isLoading, refetch } = useQuery<SystemStatsResponse>({
    queryKey: ['admin', 'system'],
    queryFn: api.adminSystemStats,
  })
  const [purgeResult, setPurgeResult] = useState<PurgeResult | null>(null)
  const [purging, setPurging] = useState(false)

  async function handlePurge() {
    setPurging(true)
    try {
      const result = await api.adminPurge()
      setPurgeResult(result)
      const total = Object.values(result).reduce((a, b) => a + b, 0)
      toast.success(`Purged ${total} expired row${total !== 1 ? 's' : ''}`)
      void refetch()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setPurging(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Qdrant */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-fg-subtle">Qdrant Collections</span>
          <button onClick={() => void refetch()} className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin text-fg-muted" />
          </div>
        ) : !stats?.qdrant.length ? (
          <p className="text-xs text-fg-subtle">No Qdrant collections found</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border-default">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border-default bg-canvas-subtle">
                  <th className="px-3 py-2 text-left font-medium text-fg-muted">Collection</th>
                  <th className="px-3 py-2 text-right font-medium text-fg-muted">Points</th>
                  <th className="px-3 py-2 text-right font-medium text-fg-muted">Vectors</th>
                  <th className="px-3 py-2 text-right font-medium text-fg-muted">Segments</th>
                  <th className="px-3 py-2 text-left font-medium text-fg-muted">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-default">
                {stats.qdrant.map((col) => (
                  <tr key={col.collection_name} className="hover:bg-canvas-subtle">
                    <td className="px-3 py-2 font-mono text-fg-default">{col.collection_name}</td>
                    <td className="px-3 py-2 text-right text-fg-muted">{col.points_count.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right text-fg-muted">{col.vectors_count.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right text-fg-muted">{col.segments_count}</td>
                    <td className="px-3 py-2">
                      <span className={cn(
                        'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium',
                        col.status.includes('green') || col.status === 'CollectionStatus.Green'
                          ? 'bg-success-subtle text-success-fg'
                          : 'bg-attention-subtle text-attention-fg',
                      )}>
                        {col.status.replace('CollectionStatus.', '')}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* PostgreSQL */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-fg-subtle">PostgreSQL Tables</span>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin text-fg-muted" />
          </div>
        ) : !stats?.postgres.length ? (
          <p className="text-xs text-fg-subtle">PostgreSQL unavailable</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border-default">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border-default bg-canvas-subtle">
                  <th className="px-3 py-2 text-left font-medium text-fg-muted">Table</th>
                  <th className="px-3 py-2 text-right font-medium text-fg-muted">Rows</th>
                  <th className="px-3 py-2 text-right font-medium text-fg-muted">Size</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-default">
                {stats.postgres.map((tbl) => (
                  <tr key={tbl.table_name} className="hover:bg-canvas-subtle">
                    <td className="px-3 py-2 font-mono text-fg-default">{tbl.table_name}</td>
                    <td className="px-3 py-2 text-right text-fg-muted">
                      {tbl.row_count === -1 ? '—' : tbl.row_count.toLocaleString()}
                    </td>
                    <td className="px-3 py-2 text-right text-fg-muted">
                      {tbl.size_bytes != null ? formatBytes(tbl.size_bytes) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Maintenance */}
      <section>
        <div className="mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-fg-subtle">Maintenance</span>
        </div>
        <div className="rounded-lg border border-border-default p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-medium text-fg-default">Purge expired rows</p>
              <p className="mt-0.5 text-xs text-fg-muted">
                Delete rows past their 30-day TTL from sessions, docs, tests, security scans, and auth sessions.
              </p>
              {purgeResult && (
                <div className="mt-2 text-xs text-fg-muted space-y-0.5">
                  <div>Sessions: <span className="font-medium text-fg-default">{purgeResult.sessions_purged}</span></div>
                  <div>Docs: <span className="font-medium text-fg-default">{purgeResult.doc_rows_purged}</span></div>
                  <div>Tests: <span className="font-medium text-fg-default">{purgeResult.test_rows_purged}</span></div>
                  <div>Security scans: <span className="font-medium text-fg-default">{purgeResult.security_rows_purged}</span></div>
                  <div>Auth sessions: <span className="font-medium text-fg-default">{purgeResult.auth_sessions_purged}</span></div>
                </div>
              )}
            </div>
            <button
              onClick={() => void handlePurge()}
              disabled={purging}
              className="flex flex-shrink-0 items-center gap-1.5 rounded-md bg-danger-emphasis px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {purging ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              Purge now
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ---------------------------------------------------------------------------
// Main AdminPanel
// ---------------------------------------------------------------------------

const TAB_LABELS: Record<AdminTab, string> = {
  users: 'Users',
  repos: 'Repositories',
  system: 'System',
}

const TAB_ICONS: Record<AdminTab, ReactNode> = {
  users: <Users className="h-3.5 w-3.5" />,
  repos: <Database className="h-3.5 w-3.5" />,
  system: <Server className="h-3.5 w-3.5" />,
}

export function AdminPanel({ onClose }: { onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<AdminTab>('users')

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex h-10 flex-shrink-0 items-center justify-between border-b border-border-default px-4">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-accent-fg" />
          <span className="text-sm font-semibold text-fg-default">Admin</span>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex h-9 flex-shrink-0 items-center gap-0 border-b border-border-default px-4">
        {(['users', 'repos', 'system'] as AdminTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors capitalize',
              activeTab === tab
                ? 'border-b-2 border-accent-emphasis text-accent-fg'
                : 'text-fg-muted hover:text-fg-default',
            )}
          >
            {TAB_ICONS[tab]}
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5">
        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'repos' && <ReposTab />}
        {activeTab === 'system' && <SystemTab />}
      </div>
    </div>
  )
}
