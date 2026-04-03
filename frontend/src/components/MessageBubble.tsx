import { useState, useEffect, useRef, useId } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { User, Bot, Copy, Check, FileCode2, ChevronDown, ChevronUp } from 'lucide-react'
import { useAppStore } from '@/store/app'
import { cn } from '@/lib/utils'
import type { Message } from '@/hooks/useChat'
import type { Components } from 'react-markdown'

// ---------------------------------------------------------------------------
// Citation badge — inline code that matches "path/to/file.ext:123"
// ---------------------------------------------------------------------------

const CITATION_RE = /^([\w./-]+\.[a-zA-Z]+):(\d+)(?:-\d+)?$/

function CitationBadge({
  children,
  repoId,
}: {
  children: string
  repoId:   string
}) {
  const openSource = useAppStore((s) => s.openSource)
  const match      = CITATION_RE.exec(children)

  if (!match) {
    return (
      <code className="rounded border border-border-muted bg-canvas-subtle px-1.5 py-0.5 font-mono text-xs text-fg-default">
        {children}
      </code>
    )
  }

  const [, filePath, lineStr] = match
  return (
    <button
      onClick={() => openSource({ repoId, filePath, line: parseInt(lineStr) })}
      title={`Open ${filePath}:${lineStr}`}
      className="inline-flex cursor-pointer items-center gap-1 rounded border border-accent-fg/30 bg-accent-subtle px-1.5 py-0.5 font-mono text-xs text-accent-fg transition-colors hover:bg-accent-muted"
    >
      <FileCode2 className="h-3 w-3 flex-shrink-0" />
      {children}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Mermaid diagram block
// ---------------------------------------------------------------------------

function MermaidBlock({ chart, isStreaming }: { chart: string; isStreaming?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const uid          = useId().replace(/:/g, '')
  const [pending, setPending]     = useState<string | null>(null)
  const [fallback, setFallback]   = useState<string | null>(null)
  const [showSrc, setShowSrc]     = useState(false)
  const [copied, setCopied]       = useState(false)
  const lastSvgRef                = useRef<string | null>(null)
  const mermaidInitializedRef     = useRef(false)
  const renderCountRef            = useRef(0)

  useEffect(() => {
    let cancelled = false
    async function render() {
      if (!chart.trim()) {
        if (!cancelled && containerRef.current) containerRef.current.innerHTML = ''
        setPending(null)
        setFallback(null)
        return
      }

      // Don't attempt to render while message is still streaming
      if (isStreaming) {
        setPending('Mermaid diagram is being streamed; waiting for completion...')
        setFallback(null)
        return
      }

      try {
        const mermaid = (await import('mermaid')).default

        // Initialize mermaid only once
        if (!mermaidInitializedRef.current) {
          mermaid.initialize({
            startOnLoad: false,
            theme: 'dark',
            themeVariables: { background: 'transparent', primaryColor: '#388bfd' },
          })
          mermaidInitializedRef.current = true
        }

        // Use a monotonically-increasing render ID so that each render call
        // gets a fresh element ID.  Reusing the same ID across calls causes
        // mermaid v10/v11 to throw "An element with id X already exists" when
        // a previous render left a stale node in the DOM.
        renderCountRef.current += 1
        const renderId = `mermaid-${uid}-${renderCountRef.current}`

        // Proactively remove any stale element that mermaid may have left behind.
        document.getElementById(renderId)?.remove()

        const { svg } = await mermaid.render(renderId, chart)

        // Clean up the detached render element mermaid places in <body>.
        document.getElementById(renderId)?.remove()

        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg
          lastSvgRef.current = svg
          setPending(null)
          setFallback(null)
        }
      } catch (e) {
        if (cancelled) return
        const msg = e instanceof Error ? e.message : 'Render error'

        // Avoid noisy syntax error popups for invalid diagrams; show fallback text.
        if (lastSvgRef.current) {
          setPending('Mermaid diagram contains syntax errors; showing last valid diagram version.')
          setFallback(null)
          if (containerRef.current) {
            containerRef.current.innerHTML = lastSvgRef.current
          }
        } else {
          setPending('Mermaid diagram contains syntax errors; showing source text.')
          setFallback(chart)
          if (containerRef.current) {
            containerRef.current.innerHTML = ''
          }
        }

        console.warn('Mermaid render failed:', msg)
      }
    }

    void render()
    return () => {
      cancelled = true
    }
  }, [chart, uid, isStreaming])

  function copy() {
    navigator.clipboard.writeText(chart).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2_000)
    })
  }

  return (
    <div className="my-3 overflow-hidden rounded-lg border border-border-default text-xs">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border-default bg-canvas-overlay px-3 py-1.5">
        <span className="font-mono text-[10px] text-fg-subtle">mermaid</span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSrc((v) => !v)}
            className="flex items-center gap-1 text-[10px] text-fg-subtle transition-colors hover:text-fg-default"
          >
            {showSrc ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            {showSrc ? 'Hide source' : 'Show source'}
          </button>
          <button
            onClick={copy}
            className="flex items-center gap-1 text-[10px] text-fg-subtle transition-colors hover:text-fg-default"
          >
            {copied ? (
              <Check className="h-3 w-3 text-success-fg" />
            ) : (
              <Copy className="h-3 w-3" />
            )}
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>

      {pending && (
        <div className="px-3 py-2 text-xs text-info-fg">{pending}</div>
      )}

      {fallback && (
        <div className="px-3 py-2 text-xs text-warning-fg">
          Mermaid source could not be rendered, showing raw text:
          <pre className="mt-1 whitespace-pre-wrap text-fg-subtle">{fallback}</pre>
        </div>
      )}

      <div
        ref={containerRef}
        className="flex justify-center overflow-x-auto bg-canvas-default p-4 [&_svg]:max-w-full"
      />

      {showSrc && (
        <pre className="border-t border-border-default bg-canvas-overlay px-3 py-2 text-[0.72rem] leading-relaxed text-fg-subtle">
          {chart}
        </pre>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Code block with copy button and syntax highlighting
// ---------------------------------------------------------------------------

function CodeBlock({ language, children, isStreaming }: { language: string; children: string; isStreaming?: boolean }) {
  const [copied, setCopied] = useState(false)

  if (language === 'mermaid') {
    return <MermaidBlock chart={children} isStreaming={isStreaming} />
  }

  function copy() {
    navigator.clipboard.writeText(children).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2_000)
    })
  }

  return (
    <div className="group my-3 overflow-hidden rounded-lg border border-border-default text-xs">
      <div className="flex items-center justify-between border-b border-border-default bg-canvas-overlay px-3 py-1.5">
        <span className="font-mono text-[10px] text-fg-subtle">{language || 'code'}</span>
        <button
          onClick={copy}
          className="flex items-center gap-1 text-[10px] text-fg-subtle transition-colors hover:text-fg-default"
        >
          {copied ? (
            <Check className="h-3 w-3 text-success-fg" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>

      <SyntaxHighlighter
        language={language || 'text'}
        style={vscDarkPlus}
        PreTag="div"
        customStyle={{
          margin:     0,
          padding:    '0.75rem',
          background: '#010409',
          fontSize:   '0.72rem',
          lineHeight: '1.5',
        }}
        codeTagProps={{ style: { fontFamily: 'inherit' } }}
      >
        {children}
      </SyntaxHighlighter>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

interface Props {
  message: Message
  repoId:  string
}

export function MessageBubble({ message, repoId }: Props) {
  const isUser = message.role === 'user'

  const components: Components = {
    code({ className, children, ...props }) {
      const language = /language-(\w+)/.exec(className ?? '')?.[1] ?? ''
      const isBlock  = Boolean(className?.startsWith('language-'))
      const text     = String(children).replace(/\n$/, '')

      if (isBlock) {
        return <CodeBlock language={language} isStreaming={message.isStreaming}>{text}</CodeBlock>
      }
      return (
        <CitationBadge repoId={repoId} {...props}>
          {text}
        </CitationBadge>
      )
    },
    a({ href, children }) {
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent-fg hover:underline"
        >
          {children}
        </a>
      )
    },
    pre({ children }) {
      return <>{children}</>
    },
  }

  return (
    <div className={cn('flex gap-3 px-4 py-3', isUser && 'flex-row-reverse')}>
      {/* Avatar */}
      <div
        className={cn(
          'flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full',
          isUser
            ? 'bg-accent-emphasis text-fg-onEmphasis'
            : 'border border-border-default bg-canvas-overlay text-fg-muted',
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      {/* Bubble */}
      <div
        className={cn(
          'max-w-[84%] rounded-2xl px-4 py-2.5 text-sm',
          isUser
            ? 'rounded-tr-sm bg-accent-emphasis text-fg-onEmphasis'
            : 'rounded-tl-sm border border-border-default bg-canvas-overlay',
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        ) : (
          <div className="prose-chat">
            {message.status && (
              <div className="mb-1 flex items-center gap-2 text-xs text-fg-subtle opacity-90">
                <span className="h-2 w-2 animate-pulse rounded-full bg-accent-fg" />
                <span>{message.status}</span>
              </div>
            )}
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
              {message.content || (message.isStreaming ? '' : '')}
            </ReactMarkdown>
            {!message.isStreaming && message.inputTokens !== undefined && message.outputTokens !== undefined && (
              <div className="mt-2 flex items-center gap-2 text-xs text-fg-subtle">
                <span>Tokens: {message.inputTokens} in / {message.outputTokens} out</span>
              </div>
            )}
            {message.isStreaming && (
              <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse rounded-full bg-accent-fg align-text-bottom" />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
