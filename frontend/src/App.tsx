import { useState, useEffect } from 'react'
import { Toaster } from 'sonner'
import { Loader2 } from 'lucide-react'
import { ThemeProvider } from '@/components/ThemeProvider'
import { Sidebar } from '@/components/Sidebar'
import { ChatPanel } from '@/components/ChatPanel'
import { DocsPanel } from '@/components/DocsPanel'
import { TestsPanel } from '@/components/TestsPanel'
import { SecurityPanel } from '@/components/SecurityPanel'
import { AdminPanel } from '@/components/AdminPanel'
import { SourceViewer } from '@/components/SourceViewer'
import { EmptyState } from '@/components/EmptyState'
import { LoginPage } from '@/components/LoginPage'
import { useAppStore } from '@/store/app'
import { useAuth } from '@/hooks/useAuth'
import { cn } from '@/lib/utils'

type MainTab = 'chat' | 'docs' | 'tests' | 'security'

const TAB_LABELS: Record<MainTab, string> = {
  chat: 'Chat',
  docs: 'Docs',
  tests: 'Tests',
  security: 'Security',
}

export default function App() {
  const activeRepoId   = useAppStore((s) => s.activeRepoId)
  const sourceLocation = useAppStore((s) => s.sourceLocation)
  const theme          = useAppStore((s) => s.theme)
  const [mainTab, setMainTab] = useState<MainTab>('chat')

  const { authChecked, isAuthenticated, authUser } = useAuth()
  const [showAdmin, setShowAdmin] = useState(false)

  // Close the admin panel if the current user loses admin rights (e.g. role change
  // or a new non-admin user authenticates in the same browser session).
  useEffect(() => {
    if (authUser?.role !== 'admin') setShowAdmin(false)
  }, [authUser])

  if (!authChecked) {
    return (
      <ThemeProvider>
        <div className="flex h-screen items-center justify-center bg-canvas-default">
          <Loader2 className="h-6 w-6 animate-spin text-fg-muted" />
        </div>
        <Toaster theme={theme} position="bottom-right" richColors closeButton />
      </ThemeProvider>
    )
  }

  if (!isAuthenticated) {
    return (
      <ThemeProvider>
        <LoginPage />
        <Toaster theme={theme} position="bottom-right" richColors closeButton />
      </ThemeProvider>
    )
  }

  return (
    <ThemeProvider>
      <div className="flex h-screen overflow-hidden bg-canvas-default text-fg-default">
        <Sidebar onAdminOpen={() => setShowAdmin(true)} />

        <main className="flex flex-1 flex-col overflow-hidden">
          {showAdmin && authUser?.role === 'admin' ? (
            <AdminPanel onClose={() => setShowAdmin(false)} />
          ) : activeRepoId ? (
            <>
              {/* Tab bar */}
              <div className="flex h-10 flex-shrink-0 items-center border-b border-border-default px-4 gap-0">
                {(['chat', 'docs', 'tests', 'security'] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setMainTab(tab)}
                    className={cn(
                      'px-3 py-1.5 text-xs font-medium transition-colors capitalize',
                      mainTab === tab
                        ? 'border-b-2 border-accent-emphasis text-accent-fg'
                        : 'text-fg-muted hover:text-fg-default',
                    )}
                  >
                    {TAB_LABELS[tab]}
                  </button>
                ))}
                <span className="ml-3 text-xs text-fg-subtle font-medium">{activeRepoId}</span>
              </div>

              {/* Content — all panels stay mounted to avoid aborting in-flight streams */}
              <div className="flex flex-1 overflow-hidden">
                <div className={cn('flex flex-1 overflow-hidden', mainTab !== 'chat' && 'hidden')}>
                  <ChatPanel repoId={activeRepoId} />
                </div>
                <div className={cn('flex flex-1 overflow-hidden', mainTab !== 'docs' && 'hidden')}>
                  <DocsPanel repoId={activeRepoId} />
                </div>
                <div className={cn('flex flex-1 overflow-hidden', mainTab !== 'tests' && 'hidden')}>
                  <TestsPanel repoId={activeRepoId} />
                </div>
                <div className={cn('flex flex-1 overflow-hidden', mainTab !== 'security' && 'hidden')}>
                  <SecurityPanel repoId={activeRepoId} />
                </div>

                {sourceLocation && (
                  <SourceViewer
                    repoId={sourceLocation.repoId}
                    filePath={sourceLocation.filePath}
                    line={sourceLocation.line}
                    endLine={sourceLocation.endLine}
                  />
                )}
              </div>
            </>
          ) : (
            <EmptyState />
          )}
        </main>
      </div>

      <Toaster
        theme={theme}
        position="bottom-right"
        richColors
        closeButton
      />
    </ThemeProvider>
  )
}
