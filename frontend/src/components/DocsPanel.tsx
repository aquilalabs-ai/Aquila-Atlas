/**
 * DocsPanel — documentation generation UI.
 *
 * Two tabs:
 *   Generate — scope/style/language form → progress bar → file browser + content viewer
 *   Saved    — list of persisted docs (with delete)
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  ArrowLeft,
  ClipboardCopy,
  Download,
  FileText,
  Folder,
  FolderOpen,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, DocContentResponse, DocLanguage, DocMetadata, DocScope, DocStyle } from '@/lib/api'
import { useDocGeneration } from '@/hooks/useDocGeneration'
import { cn } from '@/lib/utils'
import AQUILA_SVG_SYMBOL from '@/assets/images/aquila-text.svg?raw'

// ---------------------------------------------------------------------------
// Tree navigation types + builder
// ---------------------------------------------------------------------------

interface TreeNode {
  name: string
  path: string
  type: 'file' | 'folder'
  children?: TreeNode[]
}

interface IntermediateNode {
  name: string
  path: string
  type: 'file' | 'folder'
  children?: Record<string, IntermediateNode>
}

function buildFileTree(files: Record<string, string>): TreeNode[] {
  const root: Record<string, IntermediateNode> = {}

  for (const filePath of Object.keys(files)) {
    const parts = filePath.replace(/\\/g, '/').split('/')
    let current = root
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      const currentPath = parts.slice(0, i + 1).join('/')
      if (!current[part]) {
        current[part] = {
          name: part,
          path: currentPath,
          type: i === parts.length - 1 ? 'file' : 'folder',
          children: i < parts.length - 1 ? {} : undefined,
        }
      }
      if (i < parts.length - 1) {
        current = current[part].children!
      }
    }
  }

  function toArray(obj: Record<string, IntermediateNode>): TreeNode[] {
    return Object.values(obj)
      .map((n) => ({
        name: n.name,
        path: n.path,
        type: n.type,
        children: n.children ? toArray(n.children) : undefined,
      }))
      .sort((a, b) => {
        if (a.type !== b.type) return a.type === 'folder' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
  }

  return toArray(root)
}

function getAncestorPaths(filePath: string): string[] {
  const parts = filePath.replace(/\\/g, '/').split('/')
  const ancestors: string[] = []
  for (let i = 1; i < parts.length; i++) {
    ancestors.push(parts.slice(0, i).join('/'))
  }
  return ancestors
}

// ---------------------------------------------------------------------------
// Search helpers
// ---------------------------------------------------------------------------

interface SearchMatch {
  file: string
  lineNumber: number
  lineText: string
}

function searchAllFiles(files: Record<string, string>, query: string): SearchMatch[] {
  if (!query.trim()) return []
  const q = query.toLowerCase()
  const results: SearchMatch[] = []

  for (const [file, content] of Object.entries(files)) {
    const lines = content.split('\n')
    let matchesInFile = 0
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].toLowerCase().includes(q)) {
        results.push({ file, lineNumber: i + 1, lineText: lines[i].trim() })
        matchesInFile++
        if (matchesInFile >= 4) break
      }
    }
    if (results.length >= 120) break
  }

  return results
}

// Group search results by file
function groupByFile(matches: SearchMatch[]): Map<string, SearchMatch[]> {
  const map = new Map<string, SearchMatch[]>()
  for (const m of matches) {
    if (!map.has(m.file)) map.set(m.file, [])
    map.get(m.file)!.push(m)
  }
  return map
}

// Highlight the query term in a line of text
function HighlightedLine({ text, query }: { text: string; query: string }) {
  if (!query) return <span>{text}</span>
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return <span>{text}</span>
  return (
    <span>
      {text.slice(0, idx)}
      <mark className="bg-yellow-200 text-yellow-900 rounded-sm">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </span>
  )
}

// ---------------------------------------------------------------------------
// HTML export helpers (client-side, using jszip + marked)
// ---------------------------------------------------------------------------

/** Compute relative path from a nested html file back to root index.html */
function relativeIndexPath(htmlName: string): string {
  const depth = htmlName.split('/').length - 1
  return depth === 0 ? 'index.html' : '../'.repeat(depth) + 'index.html'
}

/** GitHub-flavored markdown CSS used in every content page */
const CONTENT_CSS = `<style>
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;padding:0;height:100%}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  font-size:14px;line-height:1.6;color:#1f2328;background:#fff;
  padding:2rem 2.5rem;max-width:960px}
h1{font-size:2em;border-bottom:2px solid #d0d7de;padding-bottom:.4em;margin-top:0}
h2{font-size:1.5em;border-bottom:1px solid #d0d7de;padding-bottom:.3em;margin-top:1.5em}
h3{font-size:1.25em;margin-top:1.2em}
h4{font-size:1em;margin-top:1em}
a{color:#0969da;text-decoration:none}
a:hover{text-decoration:underline}
p{margin:.5em 0 1em}
ul,ol{padding-left:1.5em;margin:.5em 0 1em}
li{margin:.2em 0}
code{font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;
  background:#f6f8fa;border:1px solid #d0d7de;
  padding:.1em .35em;border-radius:4px;font-size:.875em}
pre{background:#161b22;color:#e6edf3;padding:1.2em 1.4em;
  border-radius:8px;overflow-x:auto;margin:1em 0}
pre code{background:none;border:none;padding:0;font-size:.85em;color:inherit}
blockquote{color:#636c76;border-left:4px solid #d0d7de;
  margin:.8em 0;padding:.4em 1em;background:#f6f8fa;
  border-radius:0 4px 4px 0}
table{border-collapse:collapse;width:100%;margin:1em 0}
th,td{border:1px solid #d0d7de;padding:7px 13px;text-align:left}
th{background:#f6f8fa;font-weight:600}
tr:nth-child(even) td{background:#f6f8fa}
img{max-width:100%;height:auto;border-radius:4px}
hr{border:none;border-top:1px solid #d0d7de;margin:2em 0}
.breadcrumb{font-size:.8em;color:#636c76;margin-bottom:1.5em;
  padding:.4em .8em;background:#f6f8fa;border:1px solid #d0d7de;
  border-radius:6px;display:inline-flex;align-items:center;gap:.4em}
.breadcrumb a{color:#0969da}
.breadcrumb a:hover{text-decoration:underline}
</style>`

function buildHtmlPage(title: string, bodyHtml: string, htmlName: string): string {
  const idxPath = relativeIndexPath(htmlName)
  const nav = `<div class="breadcrumb">
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#636c76" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9,22 9,12 15,12 15,22"/></svg>
  <a href="${idxPath}" target="_parent">Index</a>
  <span style="color:#d0d7de">/</span>
  <span style="color:#1f2328;font-weight:500">${title.split('/').pop()}</span>
</div>`
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>${title}</title>
${CONTENT_CSS}
</head>
<body>
${nav}
${bodyHtml}
</body>
</html>`
}



function buildIndexHtml(
  repoId: string,
  scope: string,
  style: string,
  language: string,
  files: { htmlName: string; mdName: string }[],
): string {
  const filesJson = JSON.stringify(files.map((f) => f.htmlName))

  // Lucide-style SVG icons as inline strings (no dependencies)
  const SVG_CHEVRON_RIGHT = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9,18 15,12 9,6"/></svg>'
  const SVG_CHEVRON_DOWN  = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6,9 12,15 18,9"/></svg>'
  const SVG_FOLDER        = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#6cb6ff" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>'
  const SVG_FOLDER_OPEN   = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#6cb6ff" stroke-width="2"><path d="M5 19a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4l2 2h9a2 2 0 0 1 2 2v1"/><path d="M5 19h14a2 2 0 0 0 2-2v-5a2 2 0 0 0-2-2H9a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2z"/></svg>'
  const SVG_FILE          = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="opacity:.6"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg>'

  const logoContent = AQUILA_SVG_SYMBOL
    .replace(/<\?xml[^>]*>/g, '')
    .replace(/<!DOCTYPE[^>]*>/g, '')
    .trim()
  const logoEscaped = logoContent.replace(/'/g, "\\'").replace(/\n/g, ' ')

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Documentation \u2014 ${repoId}</title>
<style>
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;padding:0;height:100%;overflow:hidden}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  font-size:13px;color:#1f2328;background:#fff;display:flex;flex-direction:column}
.header{flex-shrink:0;display:flex;align-items:center;gap:8px;
  height:40px;padding:0 12px;border-bottom:1px solid #d0d7de;background:#fff}
.header-title{font-weight:600;font-size:13px;color:#1f2328}
.badge{display:inline-block;padding:1px 7px;border-radius:4px;font-size:10px;font-weight:500}
.badge-accent{background:#ddf4ff;color:#0550ae;border:1px solid #b6e3ff}
.badge-muted{background:#f6f8fa;color:#636c76;border:1px solid #d0d7de}
.layout{flex:1;display:flex;overflow:hidden}
.sidebar{width:210px;flex-shrink:0;display:flex;flex-direction:column;
  border-right:1px solid #d0d7de;background:#f6f8fa;overflow:hidden}
.sidebar-tree{flex:1;overflow-y:auto;padding:4px}
.tree-btn{display:flex;align-items:center;gap:5px;width:100%;
  background:none;border:none;cursor:pointer;padding:2px 4px;
  border-radius:4px;color:#636c76;font-size:11px;font-family:inherit;
  text-align:left;transition:background .1s,color .1s;white-space:nowrap}
.tree-btn:hover{background:#eaeef2;color:#1f2328}
.tree-btn.selected{background:#ddf4ff;color:#0550ae;font-weight:500}
.tree-btn .label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tree-btn .arrow{flex-shrink:0;color:#636c76}
.folder-children{display:none}
.folder-children.open{display:block}
.content{flex:1;overflow:hidden;display:flex;flex-direction:column}
iframe{flex:1;border:none;width:100%;height:100%}
.empty{flex:1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:16px}
.empty-logo{opacity:.85}
.empty-text{font-size:11px;color:#8c959f;letter-spacing:.01em}
</style>
</head>
<body>
<div class="header">
  <span class="header-title">${repoId}</span>
  <span class="badge badge-accent">${scope}</span>
  <span class="badge badge-muted">${style}</span>
  <span class="badge badge-muted">${language}</span>
</div>
<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-tree" id="tree"></div>
  </aside>
  <main class="content">
    <div class="empty" id="empty">
      <div class="empty-logo" id="logo"></div>
      <span class="empty-text">Select a file from the sidebar</span>
    </div>
    <iframe id="frame" style="display:none" name="content"></iframe>
  </main>
</div>
<script>
(function(){
var FILES = ${filesJson};
var CHEVRON_RIGHT = '${SVG_CHEVRON_RIGHT}';
var CHEVRON_DOWN  = '${SVG_CHEVRON_DOWN}';
var FOLDER_SVG    = '${SVG_FOLDER}';
var FOLDER_OPEN   = '${SVG_FOLDER_OPEN}';
var FILE_SVG      = '${SVG_FILE}';
var LOGO_HTML     = '${logoEscaped}';

document.getElementById('logo').innerHTML = LOGO_HTML;

function buildTree(paths) {
  var root = { type:'folder', name:'', path:'', children:{} };
  paths.forEach(function(p) {
    var parts = p.split('/');
    var node = root;
    for (var i = 0; i < parts.length; i++) {
      var name = parts[i];
      if (!node.children[name]) {
        node.children[name] = {
          name: name,
          path: parts.slice(0, i+1).join('/'),
          type: i === parts.length-1 ? 'file' : 'folder',
          children: {}
        };
      }
      node = node.children[name];
    }
  });
  return root;
}

function sortedChildren(node) {
  return Object.values(node.children).sort(function(a, b) {
    if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
}

var selectedBtn = null;

function selectFile(path, btn) {
  if (selectedBtn) selectedBtn.classList.remove('selected');
  selectedBtn = btn;
  btn.classList.add('selected');
  document.getElementById('frame').src = path;
  document.getElementById('frame').style.display = 'block';
  document.getElementById('empty').style.display = 'none';
}

function renderNode(node, depth, container) {
  sortedChildren(node).forEach(function(child) {
    var btn = document.createElement('button');
    btn.className = 'tree-btn';
    btn.style.paddingLeft = (depth * 12 + 4) + 'px';

    if (child.type === 'folder') {
      var arrowSpan = document.createElement('span');
      arrowSpan.className = 'arrow';
      arrowSpan.innerHTML = CHEVRON_RIGHT;
      var folderIcon = document.createElement('span');
      folderIcon.innerHTML = FOLDER_SVG;
      var label = document.createElement('span');
      label.className = 'label';
      label.textContent = child.name;
      btn.appendChild(arrowSpan);
      btn.appendChild(folderIcon);
      btn.appendChild(label);

      var childWrap = document.createElement('div');
      childWrap.className = 'folder-children';

      btn.addEventListener('click', function() {
        var isOpen = childWrap.classList.contains('open');
        childWrap.classList.toggle('open');
        arrowSpan.innerHTML = isOpen ? CHEVRON_RIGHT : CHEVRON_DOWN;
        folderIcon.innerHTML = isOpen ? FOLDER_SVG : FOLDER_OPEN;
      });

      container.appendChild(btn);
      renderNode(child, depth + 1, childWrap);
      container.appendChild(childWrap);
    } else {
      btn.innerHTML = FILE_SVG + '<span class="label">' + child.name + '</span>';
      btn.addEventListener('click', function() { selectFile(child.path, btn); });
      container.appendChild(btn);
    }
  });
}

window.addEventListener('DOMContentLoaded', function() {
  var tree = buildTree(FILES);
  renderNode(tree, 0, document.getElementById('tree'));
});
})();
</script>
</body>
</html>`
}

// ---------------------------------------------------------------------------
// TreeNode component
// ---------------------------------------------------------------------------

function FileTreeNode({
  node,
  depth,
  selectedFile,
  expandedFolders,
  onSelectFile,
  onToggleFolder,
}: {
  node: TreeNode
  depth: number
  selectedFile: string
  expandedFolders: Set<string>
  onSelectFile: (path: string) => void
  onToggleFolder: (path: string) => void
}) {
  const isExpanded = expandedFolders.has(node.path)

  if (node.type === 'folder') {
    return (
      <div>
        <button
          onClick={() => onToggleFolder(node.path)}
          className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-xs text-fg-muted transition-colors hover:bg-canvas-subtle hover:text-fg-default"
          style={{ paddingLeft: `${depth * 12 + 4}px` }}
        >
          {isExpanded ? (
            <ChevronDown className="h-3 w-3 flex-shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 flex-shrink-0" />
          )}
          {isExpanded ? (
            <FolderOpen className="h-3 w-3 flex-shrink-0 text-accent-fg" />
          ) : (
            <Folder className="h-3 w-3 flex-shrink-0 text-accent-fg" />
          )}
          <span className="truncate">{node.name}</span>
        </button>
        {isExpanded && node.children && (
          <div>
            {node.children.map((child) => (
              <FileTreeNode
                key={child.path}
                node={child}
                depth={depth + 1}
                selectedFile={selectedFile}
                expandedFolders={expandedFolders}
                onSelectFile={onSelectFile}
                onToggleFolder={onToggleFolder}
              />
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <button
      onClick={() => onSelectFile(node.path)}
      className={cn(
        'flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-xs transition-colors',
        selectedFile === node.path
          ? 'bg-accent-subtle font-medium text-accent-fg'
          : 'text-fg-muted hover:bg-canvas-subtle hover:text-fg-default',
      )}
      style={{ paddingLeft: `${depth * 12 + 4}px` }}
    >
      <span className="h-3 w-3 flex-shrink-0" />
      <FileText className="h-3 w-3 flex-shrink-0 opacity-60" />
      <span className="truncate">{node.name}</span>
    </button>
  )
}

// ---------------------------------------------------------------------------
// DocResult — file browser + content viewer (done state)
// ---------------------------------------------------------------------------

function DocResult({
  repoId,
  jobId,
  files,
  scope,
  style,
  language,
  onBack,
}: {
  repoId: string
  jobId: string
  files: Record<string, string>
  scope: string
  style: string
  language: string
  onBack: () => void
}) {
  const tree = buildFileTree(files)
  const firstFile = Object.keys(files).sort()[0] ?? ''
  const [selectedFile, setSelectedFile] = useState(firstFile)
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(
    new Set(getAncestorPaths(firstFile)),
  )

  // Search state
  const [searchQuery, setSearchQuery] = useState('')
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Export dropdown state
  const [showExportMenu, setShowExportMenu] = useState(false)
  const exportMenuRef = useRef<HTMLDivElement>(null)

  // Close export menu on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setShowExportMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Compute search results
  const searchResults = useMemo(
    () => searchAllFiles(files, searchQuery),
    [files, searchQuery],
  )
  const groupedResults = useMemo(() => groupByFile(searchResults), [searchResults])

  const isSearching = searchQuery.trim().length > 0

  function handleSelectFile(path: string) {
    setSelectedFile(path)
    setExpandedFolders((prev) => new Set([...prev, ...getAncestorPaths(path)]))
  }

  function handleToggleFolder(path: string) {
    setExpandedFolders((prev) => {
      const next = new Set(prev)
      next.has(path) ? next.delete(path) : next.add(path)
      return next
    })
  }

  function handleSelectSearchMatch(match: SearchMatch) {
    handleSelectFile(match.file)
  }

  async function handleCopy() {
    const content = files[selectedFile] ?? ''
    try {
      await navigator.clipboard.writeText(content)
      toast.success('Copied to clipboard')
    } catch {
      toast.error('Copy failed')
    }
  }

  function handleDownloadMd() {
    const url = api.getDocDownloadUrl(repoId, jobId)
    const a = document.createElement('a')
    a.href = url
    a.download = `${repoId}-docs-${scope}-${language}.zip`
    a.click()
    setShowExportMenu(false)
  }

  async function handleDownloadHtml() {
    setShowExportMenu(false)
    try {
      const [{ default: JSZip }, { marked }] = await Promise.all([
        import('jszip'),
        import('marked'),
      ])
      const zip = new JSZip()
      const fileIndex: { htmlName: string; mdName: string }[] = []

      for (const [filename, content] of Object.entries(files)) {
        const htmlName = filename.endsWith('.md')
          ? filename.slice(0, -3) + '.html'
          : filename + '.html'
        const title = filename
        const bodyHtml = await marked(content)
        zip.file(htmlName, buildHtmlPage(title, bodyHtml, htmlName))
        fileIndex.push({ htmlName, mdName: filename })
      }

      // Add index.html linking to all files
      zip.file('index.html', buildIndexHtml(repoId, scope, style, language, fileIndex))

      const blob = await zip.generateAsync({ type: 'blob' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${repoId}-docs-${scope}-${language}-html.zip`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('HTML documentation downloaded')
    } catch {
      toast.error('HTML export failed')
    }
  }

  const fileCount = Object.keys(files).length

  // Count matches in current file for indicator
  const matchesInCurrentFile = isSearching
    ? (groupedResults.get(selectedFile)?.length ?? 0)
    : 0

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex h-10 flex-shrink-0 items-center gap-2 border-b border-border-default px-3">
        <button
          onClick={onBack}
          title="Back"
          className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
        </button>
        <div className="flex flex-1 items-center gap-2">
          <span className="rounded bg-canvas-subtle px-1.5 py-0.5 text-[10px] font-medium text-fg-muted">
            {scope}
          </span>
          <span className="rounded bg-canvas-subtle px-1.5 py-0.5 text-[10px] font-medium text-fg-muted">
            {style}
          </span>
          <span className="rounded bg-canvas-subtle px-1.5 py-0.5 text-[10px] font-medium text-fg-muted">
            {language}
          </span>
          <span className="text-xs text-fg-subtle">
            {fileCount} file{fileCount !== 1 ? 's' : ''}
          </span>
        </div>
        <button
          onClick={() => void handleCopy()}
          title="Copy current file"
          className="rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default"
        >
          <ClipboardCopy className="h-3.5 w-3.5" />
        </button>
        {/* Export dropdown */}
        <div ref={exportMenuRef} className="relative">
          <button
            onClick={() => setShowExportMenu((v) => !v)}
            title="Export"
            className="flex items-center gap-0.5 rounded p-1 text-fg-subtle hover:bg-canvas-subtle hover:text-fg-default"
          >
            <Download className="h-3.5 w-3.5" />
            <ChevronDown className="h-2.5 w-2.5" />
          </button>
          {showExportMenu && (
            <div className="absolute right-0 top-full z-20 mt-1 w-48 overflow-hidden rounded-md border border-border-default bg-canvas-default shadow-md">
              <button
                onClick={handleDownloadMd}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-fg-default transition-colors hover:bg-canvas-subtle"
              >
                <FileText className="h-3.5 w-3.5 flex-shrink-0 opacity-60" />
                <span>Download as Markdown</span>
              </button>
              <button
                onClick={() => void handleDownloadHtml()}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-fg-default transition-colors hover:bg-canvas-subtle"
              >
                <Download className="h-3.5 w-3.5 flex-shrink-0 opacity-60" />
                <span>Download as HTML</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Split: sidebar + content */}
      <div className="flex flex-1 overflow-hidden">
        {/* File sidebar */}
        <div className="flex w-52 flex-shrink-0 flex-col border-r border-border-default">
          {/* Search input */}
          <div className="flex-shrink-0 border-b border-border-default px-2 py-1.5">
            <div className="flex items-center gap-1.5 rounded-md border border-border-default bg-canvas-subtle px-2 py-1 focus-within:border-accent-emphasis focus-within:bg-canvas-default">
              <Search className="h-3 w-3 flex-shrink-0 text-fg-subtle" />
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search docs…"
                className="min-w-0 flex-1 bg-transparent text-[11px] text-fg-default placeholder:text-fg-subtle focus:outline-none"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="flex-shrink-0 text-fg-subtle hover:text-fg-default"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>

          {/* File tree or search results */}
          <div className="flex-1 overflow-y-auto p-1">
            {isSearching ? (
              searchResults.length === 0 ? (
                <p className="px-2 py-3 text-[11px] text-fg-subtle">No matches found</p>
              ) : (
                <div className="space-y-2">
                  <p className="px-1 pt-1 text-[10px] text-fg-subtle">
                    {searchResults.length} match{searchResults.length !== 1 ? 'es' : ''}
                    {' in '}
                    {groupedResults.size} file{groupedResults.size !== 1 ? 's' : ''}
                  </p>
                  {Array.from(groupedResults.entries()).map(([file, matches]) => (
                    <div key={file}>
                      <p
                        className="truncate px-1 text-[10px] font-medium text-fg-muted"
                        title={file}
                      >
                        {file.split('/').pop()}
                      </p>
                      {matches.map((m, i) => (
                        <button
                          key={i}
                          onClick={() => handleSelectSearchMatch(m)}
                          className={cn(
                            'flex w-full flex-col gap-0.5 rounded px-1.5 py-1 text-left transition-colors',
                            selectedFile === m.file
                              ? 'bg-accent-subtle'
                              : 'hover:bg-canvas-subtle',
                          )}
                        >
                          <span className="text-[10px] text-fg-subtle">
                            line {m.lineNumber}
                          </span>
                          <span className="truncate text-[11px] text-fg-default">
                            <HighlightedLine
                              text={m.lineText.slice(0, 60)}
                              query={searchQuery}
                            />
                          </span>
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              )
            ) : (
              tree.map((node) => (
                <FileTreeNode
                  key={node.path}
                  node={node}
                  depth={0}
                  selectedFile={selectedFile}
                  expandedFolders={expandedFolders}
                  onSelectFile={handleSelectFile}
                  onToggleFolder={handleToggleFolder}
                />
              ))
            )}
          </div>
        </div>

        {/* Content viewer */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Match indicator */}
          {isSearching && matchesInCurrentFile > 0 && (
            <div className="flex flex-shrink-0 items-center gap-1.5 border-b border-border-default bg-canvas-subtle px-4 py-1">
              <Search className="h-3 w-3 text-fg-subtle" />
              <span className="text-[11px] text-fg-muted">
                {matchesInCurrentFile} match{matchesInCurrentFile !== 1 ? 'es' : ''} for{' '}
                <span className="font-medium text-fg-default">"{searchQuery}"</span> in this file
              </span>
            </div>
          )}
          <div className="flex-1 overflow-y-auto p-6">
            {selectedFile && files[selectedFile] ? (
              <div className="prose-github max-w-3xl">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    code({ className, children, ...props }) {
                      const match = /language-(\w+)/.exec(className ?? '')
                      const isBlock = !!match
                      return isBlock ? (
                        <SyntaxHighlighter
                          style={oneDark}
                          language={match[1]}
                          PreTag="div"
                          customStyle={{
                            margin: 0,
                            borderRadius: '6px',
                            fontSize: '12px',
                            lineHeight: '1.5',
                          }}
                        >
                          {String(children).replace(/\n$/, '')}
                        </SyntaxHighlighter>
                      ) : (
                        <code className={className} {...props}>
                          {children}
                        </code>
                      )
                    },
                  }}
                >
                  {files[selectedFile]}
                </ReactMarkdown>
              </div>
            ) : (
              <p className="text-xs text-fg-subtle">Select a file to view its content</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Saved docs list
// ---------------------------------------------------------------------------

function SavedDocsList({
  repoId,
  onOpen,
}: {
  repoId: string
  onOpen: (content: DocContentResponse) => void
}) {
  const [docs, setDocs] = useState<DocMetadata[]>([])
  const [loading, setLoading] = useState(true)

  async function loadDocs() {
    setLoading(true)
    try {
      const resp = await api.listRepoDocs(repoId)
      setDocs(resp.docs)
    } catch {
      setDocs([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadDocs() }, [repoId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleOpen(doc: DocMetadata) {
    try {
      const content = await api.getDocContent(repoId, doc.job_id)
      onOpen(content)
    } catch {
      toast.error('Failed to load documentation')
    }
  }

  async function handleDelete(e: React.MouseEvent, doc: DocMetadata) {
    e.stopPropagation()
    try {
      await api.deleteDoc(repoId, doc.job_id)
      toast.success('Deleted')
      void loadDocs()
    } catch {
      toast.error('Delete failed')
    }
  }

  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-md bg-canvas-subtle" />
        ))}
      </div>
    )
  }

  if (docs.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
        <BookOpen className="h-8 w-8 text-fg-subtle opacity-40" />
        <p className="text-sm text-fg-muted">No saved documentation yet</p>
        <p className="text-xs text-fg-subtle">Generate docs using the Generate tab</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-1">
      {docs.map((doc) => (
        <button
          key={doc.job_id}
          onClick={() => void handleOpen(doc)}
          className="group flex w-full items-center gap-2 rounded-md border border-border-default px-3 py-2 text-left transition-colors hover:bg-canvas-subtle"
        >
          <BookOpen className="h-4 w-4 flex-shrink-0 text-accent-fg" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="rounded bg-accent-subtle px-1 py-0.5 text-[10px] font-medium text-accent-fg">
                {doc.scope}
              </span>
              <span className="rounded bg-canvas-subtle px-1 py-0.5 text-[10px] text-fg-muted">
                {doc.style}
              </span>
              <span className="rounded bg-canvas-subtle px-1 py-0.5 text-[10px] text-fg-muted">
                {doc.language}
              </span>
            </div>
            <p className="mt-0.5 text-[10px] text-fg-subtle truncate">
              {new Date(doc.created_at).toLocaleString()}
            </p>
          </div>
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => void handleDelete(e, doc)}
            onKeyDown={(e) =>
              e.key === 'Enter' && void handleDelete(e as unknown as React.MouseEvent, doc)
            }
            className="hidden rounded p-1 text-danger-fg transition-colors hover:bg-canvas-default group-hover:block"
            title="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </span>
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Scope / style / language options
// ---------------------------------------------------------------------------

const SCOPE_OPTIONS: { value: DocScope; label: string; description: string }[] = [
  { value: 'architecture', label: 'Architecture', description: 'Single comprehensive overview of the whole codebase' },
  { value: 'per_module', label: 'Per module', description: 'One file per top-level package with public API and dependencies' },
  { value: 'per_file', label: 'Per file', description: 'One file per source file with signatures and side-effects' },
  { value: 'subsystem', label: 'Subsystems', description: "One file per import-graph community — explains each cluster's collective purpose" },
  { value: 'flows', label: 'Execution flows', description: 'One file per entry point — traces the full call chain from public functions' },
]

const STYLE_OPTIONS: { value: DocStyle; label: string }[] = [
  { value: 'technical', label: 'Technical (developer)' },
  { value: 'functional', label: 'Functional (PM / QA)' },
]

const LANGUAGE_OPTIONS: { value: DocLanguage; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'French' },
  { value: 'es', label: 'Spanish' },
  { value: 'de', label: 'German' },
  { value: 'zh', label: 'Chinese' },
  { value: 'ja', label: 'Japanese' },
  { value: 'pt', label: 'Portuguese' },
  { value: 'ar', label: 'Arabic' },
]

// ---------------------------------------------------------------------------
// Main DocsPanel
// ---------------------------------------------------------------------------

export function DocsPanel({ repoId }: { repoId: string }) {
  const { state, generate, reset, cancel, dismissOverride, loadSaved } = useDocGeneration(repoId)
  const [activeTab, setActiveTab] = useState<'generate' | 'saved'>('generate')
  const [returnTab, setReturnTab] = useState<'generate' | 'saved'>('generate')
  const [scope, setScope] = useState<DocScope>('architecture')
  const [style, setStyle] = useState<DocStyle>('technical')
  const [language, setLanguage] = useState<DocLanguage>('en')

  // When a saved doc is opened, remember to return to saved tab (poll keeps running)
  function handleOpenSaved(content: DocContentResponse) {
    setReturnTab('saved')
    loadSaved(content)
  }

  // Done state → show DocResult
  if (state.phase === 'done') {
    function handleBack() {
      if (returnTab === 'saved') {
        // User came from saved tab: just dismiss the override so the job state is shown again
        dismissOverride()
      } else {
        // User came from a completed generation: full reset
        reset()
      }
      setActiveTab(returnTab)
      setReturnTab('generate')
    }

    return (
      <DocResult
        repoId={repoId}
        jobId={state.jobId}
        files={state.files}
        scope={state.scope}
        style={state.style}
        language={state.language}
        onBack={handleBack}
      />
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex h-10 flex-shrink-0 items-center gap-0 border-b border-border-default px-3">
        {(['generate', 'saved'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-3 py-1.5 text-xs font-medium transition-colors capitalize',
              activeTab === tab
                ? 'border-b-2 border-accent-emphasis text-accent-fg'
                : 'text-fg-muted hover:text-fg-default',
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Generate tab */}
      {activeTab === 'generate' && (
        <div className="flex-1 overflow-y-auto p-4">
          {/* Polling progress */}
          {state.phase === 'polling' && (
            <div className="mb-6 space-y-3">
              <div className="flex items-center justify-between text-xs text-fg-muted">
                <span>Generating documentation…</span>
                {state.total > 0 && (
                  <span>{state.completed}/{state.total}</span>
                )}
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-canvas-subtle">
                <div
                  className="h-full rounded-full bg-accent-emphasis transition-all duration-500"
                  style={{
                    width: state.total > 0
                      ? `${Math.round((state.completed / state.total) * 100)}%`
                      : '10%',
                  }}
                />
              </div>
              {state.currentTarget && (
                <p className="text-[11px] text-fg-subtle truncate">
                  Processing: <span className="font-mono">{state.currentTarget}</span>
                </p>
              )}
              <button
                type="button"
                onClick={() => void cancel(state.jobId)}
                className="mt-1 flex items-center gap-1.5 rounded-md border border-danger-emphasis/40 px-2.5 py-1 text-xs text-danger-fg transition-colors hover:bg-danger-subtle"
              >
                <X className="h-3 w-3" />
                Cancel generation
              </button>
            </div>
          )}

          {/* Error */}
          {state.phase === 'error' && (
            <div className="mb-4 rounded-md border border-danger-emphasis bg-danger-subtle px-3 py-2 text-xs text-danger-fg">
              {state.message}
            </div>
          )}

          {/* Generation form */}
          {(state.phase === 'idle' || state.phase === 'error' || state.phase === 'submitting') && (
            <div className="space-y-5">
              {/* Scope */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-fg-default">Scope</label>
                <div className="space-y-1.5">
                  {SCOPE_OPTIONS.map((opt) => (
                    <label
                      key={opt.value}
                      className={cn(
                        'flex cursor-pointer items-start gap-2.5 rounded-md border p-2.5 transition-colors',
                        scope === opt.value
                          ? 'border-accent-emphasis bg-accent-subtle'
                          : 'border-border-default hover:bg-canvas-subtle',
                      )}
                    >
                      <input
                        type="radio"
                        name="scope"
                        value={opt.value}
                        checked={scope === opt.value}
                        onChange={() => setScope(opt.value)}
                        className="mt-0.5 accent-accent-emphasis"
                      />
                      <div>
                        <p className="text-xs font-medium text-fg-default">{opt.label}</p>
                        <p className="text-[10px] text-fg-subtle">{opt.description}</p>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              {/* Style */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-fg-default">Style</label>
                <div className="flex gap-2">
                  {STYLE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setStyle(opt.value)}
                      className={cn(
                        'flex-1 rounded-md border py-1.5 text-xs font-medium transition-colors',
                        style === opt.value
                          ? 'border-accent-emphasis bg-accent-subtle text-accent-fg'
                          : 'border-border-default text-fg-muted hover:bg-canvas-subtle',
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Language */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-fg-default">Language</label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value as DocLanguage)}
                  className="w-full rounded-md border border-border-default bg-canvas-default px-2 py-1.5 text-xs text-fg-default focus:border-accent-emphasis focus:outline-none"
                >
                  {LANGUAGE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>

              <button
                onClick={() => void generate(scope, style, language)}
                disabled={state.phase === 'submitting'}
                className="w-full rounded-md bg-accent-emphasis py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {state.phase === 'submitting' ? 'Submitting…' : 'Generate documentation'}
              </button>
            </div>
          )}

        </div>
      )}

      {/* Saved tab */}
      {activeTab === 'saved' && (
        <SavedDocsList repoId={repoId} onOpen={handleOpenSaved} />
      )}
    </div>
  )
}
