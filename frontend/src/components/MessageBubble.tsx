import { useState, useEffect, useRef, useId, useMemo, memo, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { User, Bot, Copy, Check, FileCode2, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'
import { useAppStore } from '@/store/app'
import { cn } from '@/lib/utils'
import type { Message } from '@/hooks/useChat'
import type { Components } from 'react-markdown'

// ---------------------------------------------------------------------------
// Citation badge — inline code that matches "path/to/file.ext" or "…:123" or "…:123-456"
// Also used by the anchor renderer for local markdown links.
// ---------------------------------------------------------------------------

// Known source/config file extensions — prevents identifiers like `api.fileChunks`
// from being mistaken for file citations.
const _EXTS =
  'py|tsx?|jsx?|mjs|cjs|go|rs|java|kts?|cs|cpp|cc|cxx|c|h|hpp|rb|php|swift|' +
  'scala|lua|sh|bash|zsh|ps1|mdx?|txt|rst|json|ya?ml|toml|ini|cfg|conf|env|' +
  'html?|css|scss|sass|less|vue|svelte|sql|tf|hcl|xml|proto|graphql|gql|' +
  'dockerfile|makefile|lock|mod|sum'
// Line numbers are optional; accept both regular hyphen and non-breaking hyphen (U+2011)
// Extension group is non-capturing (?:...) so match indices stay: [1]=path [2]=line [3]=endLine
const CITATION_RE = new RegExp(
  `^([\\w./-]+\\.(?:${_EXTS}))(?::(\\d+)(?:[-‑](\\d+))?)?$`,
  'i',
)

// GitHub-style anchor: path/to/file.py#L42  or  path/to/file.py#L42-L50
const GITHUB_ANCHOR_RE = /^(.+?)#L(\d+)(?:-L(\d+))?$/

/** Resolve a (possibly partial) file path against the known file list for the repo.
 *  `found` is false only when the index is loaded AND no match exists at all. */
function resolveFilePath(
  partial: string,
  files: string[],
  indexLoaded: boolean,
): { resolved: string; candidates: string[]; found: boolean } {
  // Index not yet loaded — optimistically treat as found so the badge shows
  if (!indexLoaded) return { resolved: partial, candidates: [], found: true }
  // Exact match
  if (files.includes(partial)) return { resolved: partial, candidates: [], found: true }
  // Suffix match: find all files whose path ends with /partial
  const needle  = partial.startsWith('/') ? partial : `/${partial}`
  const matches = files.filter((f) => f === partial || f.endsWith(needle))
  if (matches.length === 1) return { resolved: matches[0], candidates: [],       found: true }
  if (matches.length > 1)   return { resolved: partial,   candidates: matches,   found: true }
  // Nothing found in a loaded index
  return { resolved: partial, candidates: [], found: false }
}

function FileBadge({
  repoId,
  filePath,
  line,
  endLine,
  label,
}: {
  repoId:    string
  filePath:  string
  line?:     number
  endLine?:  number
  label?:    string
}) {
  const openSource      = useAppStore((s) => s.openSource)
  const fileIndex       = useAppStore((s) => s.fileIndex)
  const loadFileIndex   = useAppStore((s) => s.loadFileIndex)
  const [open, setOpen] = useState(false)
  const ref             = useRef<HTMLDivElement>(null)

  // Trigger index load on first render for this repo (no-op if already cached/loading)
  useEffect(() => { void loadFileIndex(repoId) }, [repoId, loadFileIndex])

  // Close picker when clicking outside
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const files       = fileIndex[repoId] ?? []
  const indexLoaded = repoId in fileIndex
  const { resolved, candidates, found } = resolveFilePath(filePath, files, indexLoaded)
  const display = label ?? (line !== undefined ? `${filePath}:${line}${endLine !== undefined ? `-${endLine}` : ''}` : filePath)

  // Index loaded and no match — render as plain inline code
  if (!found) {
    return (
      <code className="rounded border border-border-muted bg-canvas-subtle px-1.5 py-0.5 font-mono text-xs text-fg-default">
        {display}
      </code>
    )
  }

  const handleClick = useCallback(() => {
    if (candidates.length > 0) { setOpen((v) => !v); return }
    openSource({ repoId, filePath: resolved, line, endLine })
  }, [candidates.length, openSource, repoId, resolved, line, endLine])

  return (
    <span ref={ref} className="relative inline-flex">
      <button
        onClick={handleClick}
        title={candidates.length > 0 ? `Ambiguous path — click to pick` : `Open ${resolved}`}
        className="inline-flex cursor-pointer items-center gap-1 rounded border border-accent-fg/30 bg-accent-subtle px-1.5 py-0.5 font-mono text-xs text-accent-fg transition-colors hover:bg-accent-muted"
      >
        <FileCode2 className="h-3 w-3 flex-shrink-0" />
        {display}
        {candidates.length > 0 && <span className="ml-0.5 opacity-60">▾</span>}
      </button>

      {open && candidates.length > 0 && (
        <div className="absolute left-0 top-full z-50 mt-1 min-w-max rounded border border-border-default bg-canvas-overlay shadow-lg">
          {candidates.map((c) => (
            <button
              key={c}
              onClick={() => { openSource({ repoId, filePath: c, line, endLine }); setOpen(false) }}
              className="flex w-full items-center gap-1.5 px-3 py-1.5 font-mono text-xs text-fg-default hover:bg-canvas-subtle"
            >
              <FileCode2 className="h-3 w-3 flex-shrink-0 text-accent-fg" />
              {c}
            </button>
          ))}
        </div>
      )}
    </span>
  )
}

function CitationBadge({
  children,
  repoId,
}: {
  children: string
  repoId:   string
}) {
  const match = CITATION_RE.exec(children)

  if (!match) {
    return (
      <code className="rounded border border-border-muted bg-canvas-subtle px-1.5 py-0.5 font-mono text-xs text-fg-default">
        {children}
      </code>
    )
  }

  const [, filePath, lineStr, endLineStr] = match
  return (
    <FileBadge
      repoId={repoId}
      filePath={filePath}
      line={lineStr ? parseInt(lineStr) : undefined}
      endLine={endLineStr ? parseInt(endLineStr) : undefined}
    />
  )
}

// ---------------------------------------------------------------------------
// Mermaid diagram block
// ---------------------------------------------------------------------------

export function MermaidBlock({
  chart,
  isStreaming,
  silent = false,
}: {
  chart: string
  isStreaming?: boolean
  /** When true, render failures show a plain code block instead of an error message. */
  silent?: boolean
}) {
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
      // Don't attempt to render while message is still streaming — check this
      // FIRST so a partial/unclosed fence that remark parsed as a code block
      // never reaches mermaid.render() with incomplete content.
      if (isStreaming) {
        setPending('Mermaid diagram is being streamed; waiting for completion...')
        setFallback(null)
        return
      }

      if (!chart.trim()) {
        if (!cancelled && containerRef.current) containerRef.current.innerHTML = ''
        setPending(null)
        setFallback(null)
        return
      }

      // Reject content that doesn't start with a recognised diagram-type keyword.
      // This catches the case where remark-gfm produces a code node from an
      // unclosed fence whose body is still partial/invalid mid-stream.
      const DIAGRAM_KEYWORD = /^(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph|xychart|mindmap|quadrantChart|timeline|journey|block|sankey|packet|architecture|zenuml|kanban)\b/i
      if (!DIAGRAM_KEYWORD.test(chart.trim())) {
        if (!silent) {
          setPending('Waiting for diagram content...')
        }
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

        if (lastSvgRef.current) {
          // Keep the last valid SVG; only show a notice in non-silent mode
          if (!silent) {
            setPending('Mermaid diagram contains syntax errors; showing last valid diagram version.')
          }
          setFallback(null)
          if (containerRef.current) {
            containerRef.current.innerHTML = lastSvgRef.current
          }
        } else {
          // No valid render yet — fall back to source
          if (!silent) {
            setPending('Mermaid diagram contains syntax errors; showing source text.')
          }
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
  }, [chart, uid, isStreaming, silent])

  function copy() {
    navigator.clipboard.writeText(chart).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2_000)
    })
  }

  // Silent mode + render failed with no previous SVG → plain code block
  if (silent && fallback !== null && !lastSvgRef.current) {
    return (
      <pre className="my-3 overflow-x-auto rounded-lg border border-border-default bg-canvas-overlay px-3 py-2 text-[0.72rem] leading-relaxed text-fg-subtle">
        <code>{chart}</code>
      </pre>
    )
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
// Copy button — copies raw markdown text of an AI message
// ---------------------------------------------------------------------------

function CopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false)

  function copy() {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2_000)
    })
  }

  return (
    <button
      onClick={copy}
      title="Copy response"
      className="flex items-center gap-1.5 text-xs text-fg-subtle transition-colors hover:text-fg-default"
    >
      {copied ? (
        <Check className="h-3 w-3 text-success-fg" />
      ) : (
        <Copy className="h-3 w-3" />
      )}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

interface Props {
  message:       Message
  repoId:        string
  isLast?:       boolean
  onRegenerate?: () => void
}

export const MessageBubble = memo(function MessageBubble({ message, repoId, isLast, onRegenerate }: Props) {
  const isUser = message.role === 'user'

  const components = useMemo<Components>(() => ({
    code({ className, children, ...props }) {
      const language = /language-(\w+)/.exec(className ?? '')?.[1] ?? ''
      const text     = String(children).replace(/\n$/, '')
      const isBlock  = Boolean(className?.startsWith('language-')) || text.includes('\n')

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
      if (href) {
        // GitHub-style anchor: path/to/file.py#L42  or  #L42-L50
        const anchorMatch = GITHUB_ANCHOR_RE.exec(href)
        if (anchorMatch) {
          const [, filePath, lineStr, endLineStr] = anchorMatch
          return (
            <FileBadge
              repoId={repoId}
              filePath={filePath}
              line={parseInt(lineStr)}
              endLine={endLineStr ? parseInt(endLineStr) : undefined}
              label={typeof children === 'string' ? children : undefined}
            />
          )
        }
        // Bare local path (no protocol) that looks like a source file
        if (!href.startsWith('http') && !href.startsWith('//') && !href.startsWith('mailto:')) {
          const fileMatch = CITATION_RE.exec(href)
          if (fileMatch) {
            const [, filePath, lineStr, endLineStr] = fileMatch
            return (
              <FileBadge
                repoId={repoId}
                filePath={filePath}
                line={lineStr ? parseInt(lineStr) : undefined}
                endLine={endLineStr ? parseInt(endLineStr) : undefined}
                label={typeof children === 'string' ? children : undefined}
              />
            )
          }
        }
      }
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
    br() {
      return <br />
    },
  }), [message.isStreaming, repoId])

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
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={components}>
              {message.content || ''}
            </ReactMarkdown>
            {!message.isStreaming && (message.inputTokens !== undefined && message.outputTokens !== undefined) && (
              <div className="mt-2 flex items-center gap-2 text-xs text-fg-subtle">
                <span>Tokens: {message.inputTokens} in / {message.outputTokens} out</span>
              </div>
            )}
            {!message.isStreaming && (
              <div className="mt-2 flex items-center gap-3">
                <CopyButton content={message.content} />
                {isLast && onRegenerate && (
                  <button
                    onClick={onRegenerate}
                    className="flex items-center gap-1.5 text-xs text-fg-subtle transition-colors hover:text-fg-default"
                  >
                    <RefreshCw className="h-3 w-3" />
                    Regenerate
                  </button>
                )}
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
})
