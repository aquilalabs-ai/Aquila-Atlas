import { useRef, useEffect, useCallback } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import { X, FileCode2, AlertCircle } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/app'

// File-extension → Monaco language ID
const EXT_LANG: Record<string, string> = {
  py:     'python',
  ts:     'typescript',
  tsx:    'typescript',
  js:     'javascript',
  jsx:    'javascript',
  go:     'go',
  rs:     'rust',
  java:   'java',
  kt:     'kotlin',
  cs:     'csharp',
  cpp:    'cpp',
  c:      'c',
  rb:     'ruby',
  php:    'php',
  swift:  'swift',
  md:     'markdown',
  json:   'json',
  yaml:   'yaml',
  yml:    'yaml',
  toml:   'ini',
  html:   'html',
  css:    'css',
  sh:     'shell',
  bash:   'shell',
}

interface Props {
  repoId:   string
  filePath: string
  line?:    number
  endLine?: number
}

export function SourceViewer({ repoId, filePath, line, endLine }: Props) {
  const closeSource = useAppStore((s) => s.closeSource)
  const theme       = useAppStore((s) => s.theme)
  const editorRef   = useRef<Parameters<OnMount>[0] | null>(null)
  const monacoRef   = useRef<Parameters<OnMount>[1] | null>(null)
  const decorRef    = useRef<{ clear: () => void } | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['fileChunks', repoId, filePath],
    queryFn:  () => api.getFileChunks(repoId, filePath),
  })

  // Reconstruct file content preserving original line numbers.
  // Each chunk is placed at its start_line so Monaco line N == original line N,
  // making citation scroll targets accurate.
  const content = data?.chunks
    ? (() => {
        const sorted = [...data.chunks].sort((a, b) => a.start_line - b.start_line)
        const lines: string[] = []
        for (const chunk of sorted) {
          // Pad to reach this chunk's start line (1-indexed → 0-indexed array)
          while (lines.length < chunk.start_line - 1) lines.push('')
          for (const l of chunk.content.split('\n')) lines.push(l)
        }
        return lines.join('\n')
      })()
    : ''

  const ext      = filePath.split('.').pop()?.toLowerCase() ?? ''
  const language = EXT_LANG[ext] ?? 'plaintext'

  const applyScroll = useCallback((targetLine: number, targetEndLine?: number) => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    if (!editor || !monaco) return
    editor.revealLineInCenter(targetLine)
    editor.setPosition({ lineNumber: targetLine, column: 1 })
    const rangeEnd = targetEndLine ?? targetLine
    decorRef.current?.clear()
    decorRef.current = editor.createDecorationsCollection([{
      range: new monaco.Range(targetLine, 1, rangeEnd, Number.MAX_SAFE_INTEGER),
      options: {
        isWholeLine: true,
        className: 'monaco-cited-range',
        overviewRuler: { color: 'rgba(56, 139, 253, 0.6)', position: monaco.editor.OverviewRulerLane.Full },
      },
    }])
  }, [])

  // Scroll whenever line/endLine changes and the editor is already mounted
  useEffect(() => {
    if (line && editorRef.current && monacoRef.current) {
      applyScroll(line, endLine)
    }
  }, [line, endLine, applyScroll])

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor
    monacoRef.current = monaco
    if (line) {
      // Wait for first layout before scrolling so the editor has a measured height
      const disposable = editor.onDidLayoutChange(() => {
        disposable.dispose()
        applyScroll(line, endLine)
      })
    }
  }

  return (
    <aside className="flex w-[480px] flex-shrink-0 flex-col border-l border-border-default bg-canvas-overlay">
      {/* Header */}
      <div className="flex h-10 flex-shrink-0 items-center gap-2 border-b border-border-default px-3">
        <FileCode2 className="h-3.5 w-3.5 flex-shrink-0 text-fg-subtle" />
        <span
          className="flex-1 truncate font-mono text-xs text-fg-muted"
          title={filePath}
        >
          {filePath}
          {line && (
            <span className="text-accent-fg">
              :{line}{endLine && endLine !== line ? `–${endLine}` : ''}
            </span>
          )}
        </span>
        <button
          onClick={closeSource}
          className="rounded p-1 text-fg-subtle transition-colors hover:bg-canvas-subtle hover:text-fg-default"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Editor area */}
      <div className="flex-1 overflow-hidden">
        {isLoading && (
          <div className="flex h-full items-center justify-center">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-border-default border-t-accent-fg" />
          </div>
        )}

        {error && !isLoading && (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-xs text-fg-muted">
            <AlertCircle className="h-5 w-5 text-danger-fg" />
            <p>Could not load file chunks</p>
            <p className="text-[10px] opacity-60">{(error as Error).message}</p>
          </div>
        )}

        {!isLoading && !error && (
          <Editor
            height="100%"
            language={language}
            value={content}
            theme={theme === 'dark' ? 'vs-dark' : 'light'}
            onMount={handleMount}
            loading={
              <div className="flex h-full items-center justify-center">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-border-default border-t-accent-fg" />
              </div>
            }
            options={{
              readOnly:              true,
              minimap:               { enabled: false },
              fontSize:              12,
              lineNumbers:           'on',
              scrollBeyondLastLine:  false,
              wordWrap:              'on',
              folding:               true,
              renderLineHighlight:   'line',
              scrollbar:             { verticalScrollbarSize: 5, horizontalScrollbarSize: 5 },
              overviewRulerLanes:    0,
              hideCursorInOverviewRuler: true,
              overviewRulerBorder:   false,
              lineDecorationsWidth:  8,
              glyphMargin:           false,
              contextmenu:           false,
              fontFamily:            "'JetBrains Mono', 'Fira Code', monospace",
            }}
          />
        )}
      </div>

      {/* Footer note */}
      {data && !isLoading && (
        <p className="border-t border-border-default px-3 py-1.5 text-[10px] text-fg-subtle">
          Showing {data.total} indexed chunk{data.total !== 1 ? 's' : ''} — content may differ from the source file
        </p>
      )}
    </aside>
  )
}
