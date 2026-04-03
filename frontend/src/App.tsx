import { Toaster } from 'sonner'
import { ThemeProvider } from '@/components/ThemeProvider'
import { Sidebar } from '@/components/Sidebar'
import { ChatPanel } from '@/components/ChatPanel'
import { SourceViewer } from '@/components/SourceViewer'
import { EmptyState } from '@/components/EmptyState'
import { useAppStore } from '@/store/app'

export default function App() {
  const activeRepoId   = useAppStore((s) => s.activeRepoId)
  const sourceLocation = useAppStore((s) => s.sourceLocation)
  const theme          = useAppStore((s) => s.theme)

  return (
    <ThemeProvider>
      {/* Full-height flex layout */}
      <div className="flex h-screen overflow-hidden bg-canvas-default text-fg-default">
        {/* Left sidebar — always visible */}
        <Sidebar />

        {/* Main content area */}
        <main className="flex flex-1 overflow-hidden">
          {activeRepoId ? (
            <ChatPanel repoId={activeRepoId} />
          ) : (
            <EmptyState />
          )}

          {/* Source viewer slides in from the right when a citation is clicked */}
          {sourceLocation && (
            <SourceViewer
              repoId={sourceLocation.repoId}
              filePath={sourceLocation.filePath}
              line={sourceLocation.line}
            />
          )}
        </main>
      </div>

      {/* Toast notifications */}
      <Toaster
        theme={theme}
        position="bottom-right"
        richColors
        closeButton
      />
    </ThemeProvider>
  )
}
