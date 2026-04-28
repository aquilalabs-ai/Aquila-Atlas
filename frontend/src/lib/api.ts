/**
 * Typed API client for the Aquila-Atlas REST backend.
 * In development, all calls go through the Vite proxy (VITE_API_URL is empty).
 * In production, set VITE_API_URL to the deployed backend URL.
 */

// store/app.ts only has `import type` from api.ts — no runtime circular dependency.
import { useAppStore } from '@/store/app'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

function authHeaders(): Record<string, string> {
  const key = import.meta.env.VITE_API_KEY as string | undefined
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (key) h['X-API-Key'] = key
  const token = useAppStore.getState().authToken
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

// Shared promise: all concurrent 401 handlers await the same refresh instead of
// returning false immediately and calling clearAuth() while the refresh is in flight.
let _refreshPromise: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  if (_refreshPromise) return _refreshPromise
  _refreshPromise = (async (): Promise<boolean> => {
    const { authRefreshToken, clearAuth } = useAppStore.getState()
    if (!authRefreshToken) { clearAuth(); return false }
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: authRefreshToken }),
      })
      if (!res.ok) { clearAuth(); return false }
      const data = await res.json() as TokenResponse
      const { setAuth, authUser } = useAppStore.getState()
      setAuth(data.access_token, data.refresh_token, {
        user_id: data.user_id,
        email: data.email,
        display_name: authUser?.display_name ?? '',
        role: data.role,
        auth_mode: authUser?.auth_mode ?? '',
      })
      return true
    } catch {
      useAppStore.getState().clearAuth()
      return false
    }
  })().finally(() => { _refreshPromise = null })
  return _refreshPromise
}

async function request<T>(path: string, init?: RequestInit, _isRetry = false): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers ?? {}) },
  })
  if (res.status === 401 && !_isRetry) {
    const refreshed = await tryRefresh()
    if (refreshed) return request<T>(path, init, true)
    // tryRefresh already called clearAuth() on failure — fall through to throw
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(text)
  }
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Auth types
// ---------------------------------------------------------------------------

export interface AuthUser {
  user_id: string
  email: string
  display_name: string
  role: string
  auth_mode: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user_id: string
  email: string
  role: string
}

export interface LicenseStatus {
  valid: boolean
  customer_id: string
  customer_name: string
  max_seats: number
  seats_used: number
  seats_available: number
  expires_at: string
}

export interface UserInfo {
  user_id: string
  email: string
  display_name: string
  role: string
  auth_mode: string
  is_active: boolean
  created_at: string
  last_seen_at?: string
}

export interface RepoAdminInfo {
  repo_id: string
  graph_nodes: number
  graph_relationships: number
  vector_chunks: number
  files: number
  commit_sha: string | null
}

export interface TableStat {
  table_name: string
  row_count: number
  size_bytes: number | null
}

export interface QdrantStat {
  collection_name: string
  vectors_count: number
  points_count: number
  segments_count: number
  status: string
}

export interface SystemStatsResponse {
  qdrant: QdrantStat[]
  postgres: TableStat[]
}

export interface PurgeResult {
  sessions_purged: number
  doc_rows_purged: number
  test_rows_purged: number
  security_rows_purged: number
  auth_sessions_purged: number
}

export interface RepoMemberInfo {
  user_id: string
  email: string
  display_name: string
  role: string
}

// ---------------------------------------------------------------------------
// Response types (mirrors aquila_atlas/api/models.py)
// ---------------------------------------------------------------------------

export interface RepoListResponse {
  repos: string[]
  total: number
}

export interface RepoStatsResponse {
  repo_id: string
  Repository: number
  File: number
  Class: number
  Function: number
  Method: number
  relationships: number
  chunks: number
  files: number
  commit_sha: string | null
}

export interface IngestResponse {
  job_id: string
  repo_id: string
  status: string
}

export type JobStatusKind = 'queued' | 'running' | 'done' | 'failed'

export interface JobStatus {
  job_id: string
  repo_id: string
  status: JobStatusKind
  files?: number
  chunks?: number
  error?: string
  ingest_type?: 'full' | 'resync'
  changed_files?: number
  old_commit_sha?: string
  new_commit_sha?: string
}

export interface ResyncResponse {
  job_id: string
  repo_id: string
  status: string
}

export interface SearchResult {
  file_path: string
  start_line: number
  end_line: number
  chunk_type: string
  qualified_name: string
  language: string
  score: number
  content: string
}

export interface SearchResponse {
  query: string
  repo_id: string
  results: SearchResult[]
  total: number
}

export interface ChatResponse {
  response: string
  session_id: string
}

export interface FileChunk {
  file_path: string
  chunk_type: string
  start_line: number
  end_line: number
  qualified_name: string
  language: string
  chunk_index: number
  chunk_total: number
  content: string
}

export interface FileChunksResponse {
  repo_id: string
  file_path: string
  chunks: FileChunk[]
  total: number
}

export interface DeleteRepoResponse {
  repo_id: string
  graph_nodes_deleted: number
  vector_chunks_deleted: number
}

// ---------------------------------------------------------------------------
// Documentation generation
// ---------------------------------------------------------------------------

export type DocScope    = 'architecture' | 'per_module' | 'per_file' | 'subsystem' | 'flows' | 'user_guide' | 'developer_guide'
export type DocStyle    = 'technical' | 'functional'
export type DocLanguage = 'en' | 'fr' | 'es' | 'de' | 'zh' | 'ja' | 'pt' | 'ar'

export interface DocGenRequest {
  scope: DocScope
  style: DocStyle
  language: DocLanguage
  targets?: string[]
  exclude_extensions?: string[]
}

export interface DocGenResponse {
  job_id: string
  repo_id: string
  status: string
}

export type DocJobStatusKind = 'queued' | 'running' | 'done' | 'failed'

export interface DocJobStatus {
  job_id: string
  repo_id: string
  scope: string
  style: string
  language: string
  status: DocJobStatusKind
  completed?: number
  total?: number
  current_target?: string
  error?: string
  files?: string[]
}

export interface DocMetadata {
  job_id: string
  repo_id: string
  scope: string
  style: string
  language: string
  created_at: string
}

export interface DocContentResponse {
  job_id: string
  repo_id: string
  scope: string
  style: string
  language: string
  files: Record<string, string>
}

// ---------------------------------------------------------------------------
// Test generation
// ---------------------------------------------------------------------------

export type TestScope = 'per_file' | 'per_module' | 'entry_points'

export interface TestGenRequest {
  scope: TestScope
  language_filter?: string[]
  exclude_extensions?: string[]
}

export interface TestGenResponse {
  job_id: string
  repo_id: string
  status: string
}

export type TestJobStatusKind = 'queued' | 'running' | 'done' | 'failed'

export interface TestJobStatus {
  job_id: string
  repo_id: string
  scope: string
  language_filter?: string[]
  status: TestJobStatusKind
  completed?: number
  total?: number
  current_target?: string
  error?: string
  files?: string[]
}

export interface TestMetadata {
  job_id: string
  repo_id: string
  scope: string
  language_filter?: string[]
  created_at: string
}

export interface TestContentResponse {
  job_id: string
  repo_id: string
  scope: string
  language_filter?: string[]
  files: Record<string, string>
  file_statuses?: Record<string, string>
}

// ---------------------------------------------------------------------------
// Security scanning
// ---------------------------------------------------------------------------

export interface SecurityFinding {
  file: string
  line: number
  rule_id: string
  severity: 'minor' | 'major' | 'critical'
  message: string
  cwe: string
  owasp_category: string
  fix_suggestion: string
  source: 'semgrep' | 'gitleaks' | 'trivy' | 'checkov' | 'llm'
  confirmed_by_llm: boolean
}

export interface SecurityScanRequest {
  source: string
  token?: string
  branch?: string
  semgrep_config?: string
  run_llm_triage?: boolean
}

export interface SecurityScanJob {
  job_id: string
  repo_id: string
  source: string
  status: 'queued' | 'running' | 'done' | 'failed'
  completed: number
  total: number
  current_phase: string | null
  error: string | null
  severity_counts: Record<string, number>
}

export interface SecurityReport {
  job_id: string
  repo_id: string
  source: string
  findings: SecurityFinding[]
  report: string
  severity_counts: Record<string, number>
  tools_used: string[]
  created_at?: string
}

export interface SecurityScanMeta {
  job_id: string
  repo_id: string
  source: string
  severity_counts: Record<string, number>
  created_at: string
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export interface SessionInfo {
  session_id: string
  repo_id: string
  title: string
  created_at: string
  message_count: number
}

export interface SessionListResponse {
  repo_id: string
  sessions: SessionInfo[]
  total: number
}

export interface SessionCreateResponse {
  session_id: string
  repo_id: string
  title: string
  created_at: string
}

// ---------------------------------------------------------------------------
// API surface
// ---------------------------------------------------------------------------

export const api = {
  // Health
  health: () => request<{ status: string; version: string }>('/health'),
  ready:  () => request<{ status: string; neo4j: boolean; qdrant: boolean }>('/health/ready'),

  // Repos
  listRepos:   () => request<RepoListResponse>('/repos'),
  getRepoStats: (repoId: string) =>
    request<RepoStatsResponse>(`/repos/${encodeURIComponent(repoId)}/stats`),
  getRepoSource: (repoId: string) =>
    request<{ path: string; source_type: string; has_token: boolean }>(
      `/repos/${encodeURIComponent(repoId)}/source`,
    ),
  deleteRepo: (repoId: string, opts?: { deleteSessions?: boolean; deleteDocs?: boolean }) => {
    const params = new URLSearchParams()
    if (opts?.deleteSessions) params.set('delete_sessions', 'true')
    if (opts?.deleteDocs) params.set('delete_docs', 'true')
    const qs = params.toString()
    return request<DeleteRepoResponse>(
      `/repos/${encodeURIComponent(repoId)}${qs ? `?${qs}` : ''}`,
      { method: 'DELETE' },
    )
  },

  // Ingestion
  ingest: (opts: { repo_id: string; source_type: string; path?: string; github_token?: string }) =>
    request<IngestResponse>('/repos', {
      method: 'POST',
      body: JSON.stringify(opts),
    }),
  uploadZip: async (repoId: string, file: File): Promise<IngestResponse> => {
    const form = new FormData()
    form.append('repo_id', repoId)
    form.append('file', file)
    const headers = authHeaders()
    delete headers['Content-Type'] // let browser set multipart boundary
    const res = await fetch(`${BASE}/repos/upload`, { method: 'POST', headers, body: form })
    if (!res.ok) { const text = await res.text().catch(() => res.statusText); throw new Error(text) }
    return res.json() as Promise<IngestResponse>
  },
  getRepoStatus: (repoId: string) =>
    request<JobStatus>(`/repos/${encodeURIComponent(repoId)}/status`),
  getJob: (jobId: string) =>
    request<JobStatus>(`/jobs/${encodeURIComponent(jobId)}`),
  resyncRepo: (repoId: string, opts: { path: string; source_type: string; github_token?: string }) => {
    const params = new URLSearchParams({ path: opts.path, source_type: opts.source_type })
    if (opts.github_token) params.set('github_token', opts.github_token)
    return request<ResyncResponse>(
      `/repos/${encodeURIComponent(repoId)}/resync?${params.toString()}`,
      { method: 'POST' },
    )
  },

  // Search
  search: (repoId: string, q: string, topK = 10) =>
    request<SearchResponse>(
      `/repos/${encodeURIComponent(repoId)}/search?q=${encodeURIComponent(q)}&top_k=${topK}`,
    ),

  // Chat (non-streaming fallback)
  chatJson: (repoId: string, message: string, sessionId?: string) =>
    request<ChatResponse>(`/repos/${encodeURIComponent(repoId)}/chat`, {
      method: 'POST',
      body: JSON.stringify({ message, session_id: sessionId, stream: false }),
    }),

  // Sessions
  listSessions: (repoId: string) =>
    request<SessionListResponse>(`/repos/${encodeURIComponent(repoId)}/sessions`),
  createSession: (repoId: string, title = 'New Chat') =>
    request<SessionCreateResponse>(`/repos/${encodeURIComponent(repoId)}/sessions`, {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),
  getSessionMessages: (repoId: string, sessionId: string) =>
    request<{ role: 'user' | 'assistant'; content: string }[]>(
      `/repos/${encodeURIComponent(repoId)}/sessions/${encodeURIComponent(sessionId)}/messages`,
    ),

  deleteSession: (repoId: string, sessionId: string) =>
    request<{ session_id: string; deleted: boolean }>(
      `/repos/${encodeURIComponent(repoId)}/sessions/${encodeURIComponent(sessionId)}`,
      { method: 'DELETE' },
    ),
  resetSession: (repoId: string, sessionId: string) =>
    request<{ session_id: string; cleared: boolean }>(
      `/repos/${encodeURIComponent(repoId)}/sessions/${encodeURIComponent(sessionId)}/reset`,
      { method: 'POST' },
    ),

  // Files
  listFiles: (repoId: string) =>
    request<{ repo_id: string; files: string[]; total: number }>(
      `/repos/${encodeURIComponent(repoId)}/files`,
    ),

  getFileChunks: (repoId: string, filePath: string) =>
    request<FileChunksResponse>(
      `/repos/${encodeURIComponent(repoId)}/files/${filePath
        .split('/')
        .map(encodeURIComponent)
        .join('/')}`,
    ),

  // Documentation generation
  generateDocs: (repoId: string, req: DocGenRequest) =>
    request<DocGenResponse>(`/repos/${encodeURIComponent(repoId)}/docs/generate`, {
      method: 'POST',
      body: JSON.stringify(req),
    }),
  getDocJobStatus: (repoId: string, jobId: string) =>
    request<DocJobStatus>(`/repos/${encodeURIComponent(repoId)}/docs/jobs/${encodeURIComponent(jobId)}`),
  getDocContent: (repoId: string, jobId: string) =>
    request<DocContentResponse>(`/repos/${encodeURIComponent(repoId)}/docs/${encodeURIComponent(jobId)}`),
  listRepoDocs: (repoId: string) =>
    request<{ repo_id: string; docs: DocMetadata[]; total: number }>(`/repos/${encodeURIComponent(repoId)}/docs`),
  cancelDocJob: (repoId: string, jobId: string) =>
    request<DocJobStatus>(`/repos/${encodeURIComponent(repoId)}/docs/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }),
  deleteDoc: (repoId: string, jobId: string) =>
    request<{ success: boolean; job_id: string; message: string }>(`/repos/${encodeURIComponent(repoId)}/docs/${encodeURIComponent(jobId)}`, { method: 'DELETE' }),
  // Test generation
  generateTests: (repoId: string, req: TestGenRequest) =>
    request<TestGenResponse>(`/repos/${encodeURIComponent(repoId)}/tests/generate`, {
      method: 'POST',
      body: JSON.stringify(req),
    }),
  getTestJobStatus: (repoId: string, jobId: string) =>
    request<TestJobStatus>(`/repos/${encodeURIComponent(repoId)}/tests/jobs/${encodeURIComponent(jobId)}`),
  cancelTestJob: (repoId: string, jobId: string) =>
    request<TestJobStatus>(`/repos/${encodeURIComponent(repoId)}/tests/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }),
  getTestContent: (repoId: string, jobId: string) =>
    request<TestContentResponse>(`/repos/${encodeURIComponent(repoId)}/tests/${encodeURIComponent(jobId)}`),
  listRepoTests: (repoId: string) =>
    request<{ repo_id: string; tests: TestMetadata[]; total: number }>(`/repos/${encodeURIComponent(repoId)}/tests`),
  deleteTest: (repoId: string, jobId: string) =>
    request<{ success: boolean; job_id: string; message: string }>(`/repos/${encodeURIComponent(repoId)}/tests/${encodeURIComponent(jobId)}`, { method: 'DELETE' }),
  getTestDownloadUrl: (repoId: string, jobId: string): string => {
    const base = (import.meta.env.VITE_API_URL as string | undefined) ?? ''
    return `${base}/repos/${encodeURIComponent(repoId)}/tests/${encodeURIComponent(jobId)}/download-zip`
  },

  getDocDownloadUrl: (repoId: string, jobId: string): string => {
    const base = (import.meta.env.VITE_API_URL as string | undefined) ?? ''
    return `${base}/repos/${encodeURIComponent(repoId)}/docs/${encodeURIComponent(jobId)}/download-zip`
  },

  // Security scanning
  submitSecurityScan: (repoId: string, req: SecurityScanRequest) =>
    request<{ job_id: string; repo_id: string; status: string }>(
      `/repos/${encodeURIComponent(repoId)}/security/scan`,
      { method: 'POST', body: JSON.stringify(req) },
    ),
  getSecurityJobStatus: (repoId: string, jobId: string) =>
    request<SecurityScanJob>(
      `/repos/${encodeURIComponent(repoId)}/security/jobs/${encodeURIComponent(jobId)}`,
    ),
  getSecurityScan: (repoId: string, jobId: string) =>
    request<SecurityReport>(
      `/repos/${encodeURIComponent(repoId)}/security/scans/${encodeURIComponent(jobId)}`,
    ),
  listSecurityScans: (repoId: string) =>
    request<{ repo_id: string; scans: SecurityScanMeta[]; total: number }>(
      `/repos/${encodeURIComponent(repoId)}/security/scans`,
    ),
  deleteSecurityScan: (repoId: string, jobId: string) =>
    request<{ success: boolean; job_id: string; message: string }>(
      `/repos/${encodeURIComponent(repoId)}/security/scans/${encodeURIComponent(jobId)}`,
      { method: 'DELETE' },
    ),
  downloadDocPdf: async (repoId: string, jobId: string): Promise<Blob> => {
    const headers = authHeaders()
    delete headers['Content-Type']
    const res = await fetch(
      `${BASE}/repos/${encodeURIComponent(repoId)}/docs/${encodeURIComponent(jobId)}/download-pdf`,
      { headers },
    )
    if (!res.ok) { const text = await res.text().catch(() => res.statusText); throw new Error(text) }
    return res.blob()
  },

  // Auth
  authCheck: async (): Promise<{ status: 200 | 401 | 501; user?: AuthUser }> => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    const token = useAppStore.getState().authToken
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`${BASE}/auth/me`, { headers })
    if (res.status === 200) return { status: 200, user: await res.json() as AuthUser }
    if (res.status === 501) return { status: 501 }
    return { status: 401 }
  },

  login: (username: string, password: string, mode: 'key' | 'ldap' = 'key') =>
    request<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password, mode }),
    }),

  activate: (seat_key: string, email: string, display_name: string, password: string) =>
    request<TokenResponse>('/auth/activate', {
      method: 'POST',
      body: JSON.stringify({ seat_key, email, display_name, password }),
    }),

  logout: (refresh_token: string) =>
    request<void>('/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ refresh_token }),
    }),

  adminGetLicense: () => request<LicenseStatus>('/admin/license'),

  // Admin — users
  adminListUsers: () => request<UserInfo[]>('/admin/users'),
  adminGetUser: (userId: string) => request<UserInfo>(`/admin/users/${encodeURIComponent(userId)}`),
  adminUpdateUser: (userId: string, body: { is_active?: boolean; role?: string; display_name?: string }) =>
    request<UserInfo>(`/admin/users/${encodeURIComponent(userId)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  adminDeleteUser: (userId: string) =>
    request<void>(`/admin/users/${encodeURIComponent(userId)}`, { method: 'DELETE' }),

  // Admin — repos
  adminListRepos: () => request<RepoAdminInfo[]>('/admin/repos'),
  adminDeleteRepo: (repoId: string) =>
    request<{ repo_id: string; graph_nodes_deleted: number; vector_chunks_deleted: number; sessions_deleted: number; docs_deleted: number }>(
      `/repos/${encodeURIComponent(repoId)}?delete_sessions=true&delete_docs=true`,
      { method: 'DELETE' },
    ),

  // Admin — repo members
  adminListRepoMembers: (repoId: string) =>
    request<RepoMemberInfo[]>(`/repos/${encodeURIComponent(repoId)}/members`),
  adminAddRepoMember: (repoId: string, email: string, role: string) =>
    request<RepoMemberInfo>(`/repos/${encodeURIComponent(repoId)}/members`, {
      method: 'POST',
      body: JSON.stringify({ email, role }),
    }),
  adminRemoveRepoMember: (repoId: string, userId: string) =>
    request<void>(`/repos/${encodeURIComponent(repoId)}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' }),

  // Admin — system stats + maintenance
  adminSystemStats: () => request<SystemStatsResponse>('/admin/system/stats'),
  adminPurge: () => request<PurgeResult>('/admin/maintenance/purge', { method: 'POST' }),
}

