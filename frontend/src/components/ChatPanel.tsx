import { useEffect, useRef } from 'react'
import { GitBranch, FileCode2, Boxes, Zap, GitFork, Library, Map } from 'lucide-react'
import { MessageBubble } from './MessageBubble'
import { ChatInput } from './ChatInput'
import { useChat } from '@/hooks/useChat'
import { useRepoStats } from '@/hooks/useRepos'
import { useAppStore } from '@/store/app'

interface Props {
  repoId: string
}

const SUGGESTIONS = [
  { icon: Map,     label: 'Architecture overview',    prompt: 'Give me a high-level architecture overview of this codebase.' },
  { icon: Zap,     label: 'Main entry points',        prompt: 'What are the main entry points of this codebase and how do they work?' },
  { icon: GitFork, label: 'Dependency diagram',       prompt: 'Draw a Mermaid flowchart showing the file-level dependency graph.' },
  { icon: Library, label: 'External libraries',       prompt: 'List all external libraries and dependencies used in this codebase.' },
  { icon: FileCode2, label: 'Key classes & modules',  prompt: 'What are the most important classes and modules? Summarise each one.' },
  { icon: GitBranch, label: 'Data flow',              prompt: 'Trace the main data flow from input to output across the codebase.' },
]

export function ChatPanel({ repoId }: Props) {
  const { messages, isLoading, send, regenerate } = useChat(repoId)
  const { data: stats }               = useRepoStats(repoId)
  const activeSessionId               = useAppStore((s) => s.activeSessions[repoId])

  const listRef   = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new messages / streaming tokens
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    if (distFromBottom < 160) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  // Scroll to bottom when switching sessions
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'instant' })
  }, [activeSessionId])

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Repo header bar */}
      <div className="flex h-10 flex-shrink-0 items-center gap-2 border-b border-border-default px-4">
        <GitBranch className="h-3.5 w-3.5 text-fg-subtle" />
        <span className="text-sm font-medium text-fg-default">{repoId}</span>
        {stats && (
          <div className="ml-auto flex items-center gap-3 text-xs text-fg-subtle">
            <span className="flex items-center gap-1">
              <FileCode2 className="h-3 w-3" />
              {stats.files}f
            </span>
            <span className="flex items-center gap-1">
              <Boxes className="h-3 w-3" />
              {stats.chunks}c
            </span>
          </div>
        )}
      </div>

      {/* Message list */}
      <div ref={listRef} className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-6 p-8 text-center">
            <div className="flex flex-col gap-1">
              <p className="text-sm font-medium text-fg-default">
                Ready to answer questions about <span className="text-accent-fg">{repoId}</span>
              </p>
              <p className="text-xs text-fg-muted">
                Ask anything about the code, or pick a suggestion below
              </p>
            </div>

            {/* Suggestion chips */}
            <div className="grid w-full max-w-lg grid-cols-2 gap-2">
              {SUGGESTIONS.map(({ icon: Icon, label, prompt }) => (
                <button
                  key={label}
                  onClick={() => send(prompt)}
                  disabled={isLoading}
                  className="flex items-center gap-2 rounded-lg border border-border-default bg-canvas-overlay px-3 py-2 text-left text-xs text-fg-default transition-colors hover:border-accent-fg hover:bg-canvas-subtle disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Icon className="h-3.5 w-3.5 flex-shrink-0 text-accent-fg" />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="py-2">
            {messages.map((msg, i) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                repoId={repoId}
                isLast={i === messages.length - 1}
                onRegenerate={regenerate}
              />
            ))}
            <div ref={bottomRef} className="h-2" />
          </div>
        )}
      </div>

      {/* Input */}
      <ChatInput onSend={send} isLoading={isLoading} />
    </div>
  )
}
