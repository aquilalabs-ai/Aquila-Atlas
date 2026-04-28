import { useState, useRef } from 'react'
import { toast } from 'sonner'
import { LogIn, KeyRound, Eye, EyeOff, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/app'
import { cn } from '@/lib/utils'

type Tab = 'signin' | 'activate'
type LoginMode = 'key' | 'ldap'

export function LoginPage() {
  const [tab, setTab]           = useState<Tab>('signin')
  const [mode, setMode]         = useState<LoginMode>('key')
  const [loading, setLoading]   = useState(false)
  const [showPwd, setShowPwd]   = useState(false)
  const [showPwd2, setShowPwd2] = useState(false)
  const [error, setError]       = useState('')

  // Sign-in fields
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  // Activate fields
  const [seatKey, setSeatKey]         = useState('')
  const [actEmail, setActEmail]       = useState('')
  const [actName, setActName]         = useState('')
  const [actPwd, setActPwd]           = useState('')
  const [actPwd2, setActPwd2]         = useState('')

  const setAuth = useAppStore((s) => s.setAuth)
  const firstInputRef = useRef<HTMLInputElement>(null)

  function handleAuthSuccess(data: Awaited<ReturnType<typeof api.login>>) {
    setAuth(data.access_token, data.refresh_token, {
      user_id:      data.user_id,
      email:        data.email,
      display_name: '',
      role:         data.role,
      auth_mode:    mode,
    })
  }

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setError('')
    setLoading(true)
    try {
      const data = await api.login(username.trim(), password, mode)
      handleAuthSuccess(data)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Login failed'
      try {
        const parsed = JSON.parse(msg)
        setError(parsed.detail ?? msg)
      } catch {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleActivate(e: React.FormEvent) {
    e.preventDefault()
    if (!seatKey.trim() || !actEmail.trim() || !actPwd) return
    if (actPwd !== actPwd2) { setError('Passwords do not match'); return }
    if (actPwd.length < 8)  { setError('Password must be at least 8 characters'); return }
    setError('')
    setLoading(true)
    try {
      const data = await api.activate(seatKey.trim(), actEmail.trim(), actName.trim(), actPwd)
      toast.success('Account activated — welcome!')
      setAuth(data.access_token, data.refresh_token, {
        user_id:      data.user_id,
        email:        data.email,
        display_name: actName.trim() || actEmail.split('@')[0],
        role:         data.role,
        auth_mode:    'key',
      })
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Activation failed'
      try {
        const parsed = JSON.parse(msg)
        setError(parsed.detail ?? msg)
      } catch {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-canvas-default px-4">
      <div className="w-full max-w-md">

        {/* Logo / title */}
        <div className="mb-8 text-center">
          <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-accent-emphasis">
            <KeyRound className="h-6 w-6 text-white" />
          </div>
          <h1 className="text-xl font-semibold text-fg-default">Aquila-Atlas</h1>
          <p className="mt-1 text-sm text-fg-muted">The Atlas of your codebase</p>
        </div>

        {/* Card */}
        <div className="rounded-xl border border-border-default bg-canvas-overlay shadow-lg">

          {/* Tabs */}
          <div className="flex border-b border-border-default">
            {(['signin', 'activate'] as const).map((t) => (
              <button
                key={t}
                onClick={() => { setTab(t); setError('') }}
                className={cn(
                  'flex-1 py-3 text-sm font-medium transition-colors',
                  tab === t
                    ? 'border-b-2 border-accent-emphasis text-accent-fg'
                    : 'text-fg-muted hover:text-fg-default',
                )}
              >
                {t === 'signin' ? 'Sign In' : 'Activate Key'}
              </button>
            ))}
          </div>

          <div className="p-6">

            {/* ── Sign In ─────────────────────────────────────── */}
            {tab === 'signin' && (
              <form onSubmit={handleSignIn} className="space-y-4">

                {/* Mode toggle */}
                <div className="flex rounded-lg border border-border-default overflow-hidden text-xs font-medium">
                  {(['key', 'ldap'] as const).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setMode(m)}
                      className={cn(
                        'flex-1 py-1.5 transition-colors',
                        mode === m
                          ? 'bg-accent-emphasis text-white'
                          : 'text-fg-muted hover:text-fg-default',
                      )}
                    >
                      {m === 'key' ? 'License Key' : 'LDAP / AD'}
                    </button>
                  ))}
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-fg-muted">
                    {mode === 'ldap' ? 'Username' : 'Email'}
                  </label>
                  <input
                    ref={firstInputRef}
                    type={mode === 'key' ? 'email' : 'text'}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder={mode === 'ldap' ? 'john.doe' : 'you@company.com'}
                    required
                    autoFocus
                    className="w-full rounded-lg border border-border-default bg-canvas-default px-3 py-2 text-sm text-fg-default placeholder:text-fg-subtle focus:border-accent-emphasis focus:outline-none"
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-fg-muted">Password</label>
                  <div className="relative">
                    <input
                      type={showPwd ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                      required
                      className="w-full rounded-lg border border-border-default bg-canvas-default px-3 py-2 pr-9 text-sm text-fg-default placeholder:text-fg-subtle focus:border-accent-emphasis focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPwd((v) => !v)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-fg-muted hover:text-fg-default"
                    >
                      {showPwd ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>

                {error && <p className="rounded-lg bg-danger-subtle px-3 py-2 text-xs text-danger-fg">{error}</p>}

                <button
                  type="submit"
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent-emphasis py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
                >
                  {loading
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <LogIn className="h-4 w-4" />}
                  {loading ? 'Signing in…' : 'Sign In'}
                </button>
              </form>
            )}

            {/* ── Activate Key ────────────────────────────────── */}
            {tab === 'activate' && (
              <form onSubmit={handleActivate} className="space-y-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-fg-muted">Seat Key</label>
                  <textarea
                    value={seatKey}
                    onChange={(e) => setSeatKey(e.target.value)}
                    placeholder="Paste your seat key JWT here…"
                    required
                    rows={3}
                    autoFocus
                    className="w-full rounded-lg border border-border-default bg-canvas-default px-3 py-2 font-mono text-xs text-fg-default placeholder:text-fg-subtle focus:border-accent-emphasis focus:outline-none resize-none"
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-fg-muted">Email</label>
                  <input
                    type="email"
                    value={actEmail}
                    onChange={(e) => setActEmail(e.target.value)}
                    placeholder="you@company.com"
                    required
                    className="w-full rounded-lg border border-border-default bg-canvas-default px-3 py-2 text-sm text-fg-default placeholder:text-fg-subtle focus:border-accent-emphasis focus:outline-none"
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-fg-muted">
                    Display Name <span className="text-fg-subtle">(optional)</span>
                  </label>
                  <input
                    type="text"
                    value={actName}
                    onChange={(e) => setActName(e.target.value)}
                    placeholder="Jane Doe"
                    className="w-full rounded-lg border border-border-default bg-canvas-default px-3 py-2 text-sm text-fg-default placeholder:text-fg-subtle focus:border-accent-emphasis focus:outline-none"
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-fg-muted">Choose Password</label>
                  <div className="relative">
                    <input
                      type={showPwd ? 'text' : 'password'}
                      value={actPwd}
                      onChange={(e) => setActPwd(e.target.value)}
                      placeholder="Min. 8 characters"
                      required
                      minLength={8}
                      className="w-full rounded-lg border border-border-default bg-canvas-default px-3 py-2 pr-9 text-sm text-fg-default placeholder:text-fg-subtle focus:border-accent-emphasis focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPwd((v) => !v)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-fg-muted hover:text-fg-default"
                    >
                      {showPwd ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-fg-muted">Confirm Password</label>
                  <div className="relative">
                    <input
                      type={showPwd2 ? 'text' : 'password'}
                      value={actPwd2}
                      onChange={(e) => setActPwd2(e.target.value)}
                      placeholder="Repeat password"
                      required
                      className="w-full rounded-lg border border-border-default bg-canvas-default px-3 py-2 pr-9 text-sm text-fg-default placeholder:text-fg-subtle focus:border-accent-emphasis focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPwd2((v) => !v)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-fg-muted hover:text-fg-default"
                    >
                      {showPwd2 ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>

                {error && <p className="rounded-lg bg-danger-subtle px-3 py-2 text-xs text-danger-fg">{error}</p>}

                <button
                  type="submit"
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent-emphasis py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
                >
                  {loading
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <KeyRound className="h-4 w-4" />}
                  {loading ? 'Activating…' : 'Activate & Sign In'}
                </button>
              </form>
            )}

          </div>
        </div>

        <p className="mt-4 text-center text-xs text-fg-subtle">
          Contact your administrator to obtain a seat key.
        </p>
      </div>
    </div>
  )
}
