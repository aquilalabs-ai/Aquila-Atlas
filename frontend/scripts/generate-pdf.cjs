#!/usr/bin/env node
'use strict'

/**
 * generate-pdf.js
 * Reads combined Markdown from stdin, pre-renders Mermaid diagrams via mmdc,
 * then converts the result to a PDF with md-to-pdf (Puppeteer / headless Chrome).
 * Writes raw PDF bytes to stdout.
 *
 * Usage:
 *   echo "# Hello" | node generate-pdf.js
 *   cat doc.md | node generate-pdf.js > out.pdf
 */

const { mdToPdf } = require('md-to-pdf')
const { execFileSync, execSync } = require('child_process')
const fs = require('fs')
const path = require('path')
const os = require('os')

// mmdc lives in the sibling node_modules; on Windows npm adds a .cmd wrapper
const _mmdcBase = path.join(__dirname, '..', 'node_modules', '.bin', 'mmdc')
const MMDC = process.platform === 'win32' ? _mmdcBase + '.cmd' : _mmdcBase

// ---------------------------------------------------------------------------
// Mermaid pre-rendering
// ---------------------------------------------------------------------------

async function renderMermaidToSvg(diagram) {
  const pid = process.pid
  const ts = Date.now()
  const tmpIn  = path.join(os.tmpdir(), `aquila-mmd-in-${pid}-${ts}.mmd`)
  const tmpOut = path.join(os.tmpdir(), `aquila-mmd-out-${pid}-${ts}.svg`)
  try {
    fs.writeFileSync(tmpIn, diagram, 'utf8')
    if (process.platform === 'win32') {
      execSync(`"${MMDC}" -i "${tmpIn}" -o "${tmpOut}" -b white`, { timeout: 15000 })
    } else {
      execFileSync(MMDC, ['-i', tmpIn, '-o', tmpOut, '-b', 'white'], { timeout: 15000 })
    }
    return fs.readFileSync(tmpOut, 'utf8')
  } catch {
    return null   // fall back to fenced code block
  } finally {
    try { fs.unlinkSync(tmpIn)  } catch { /* ignore */ }
    try { fs.unlinkSync(tmpOut) } catch { /* ignore */ }
  }
}

async function preprocessMermaid(markdown) {
  // Match fenced mermaid blocks (``` may be indented up to 3 spaces per CommonMark)
  const regex = /^[ \t]{0,3}```mermaid[ \t]*\n([\s\S]*?)^[ \t]{0,3}```[ \t]*$/gm
  const matches = [...markdown.matchAll(regex)]
  if (matches.length === 0) return markdown

  const svgs = await Promise.all(matches.map(m => renderMermaidToSvg(m[1].trim())))

  // Replace from end → start so earlier indices stay valid
  let result = markdown
  for (let i = matches.length - 1; i >= 0; i--) {
    const m = matches[i]
    const svg = svgs[i]
    // Wrap the SVG in an HTML block so markdown parsers pass it through verbatim
    const replacement = svg
      ? `\n<div style="text-align:center;margin:16px 0">\n${svg}\n</div>\n`
      : `\`\`\`\n${m[1]}\`\`\``
    result = result.slice(0, m.index) + replacement + result.slice(m.index + m[0].length)
  }
  return result
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  // Read all of stdin
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  const markdown = Buffer.concat(chunks).toString('utf8')

  const processed = await preprocessMermaid(markdown)

  const pdf = await mdToPdf(
    { content: processed },
    {
      launch_options: {
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
      },
      body_class: 'markdown-body',
      css: `
        body {
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
          font-size: 13px;
          line-height: 1.6;
          color: #1f2328;
          max-width: none;
          padding: 0;
        }
        h1 {
          font-size: 1.9em;
          border-bottom: 1px solid #d0d7de;
          padding-bottom: 0.3em;
          margin-top: 24px;
          margin-bottom: 16px;
        }
        h2 {
          font-size: 1.5em;
          border-bottom: 1px solid #d0d7de;
          padding-bottom: 0.3em;
          margin-top: 24px;
          margin-bottom: 16px;
        }
        h3 { font-size: 1.25em; margin-top: 24px; margin-bottom: 16px; }
        h4, h5, h6  { margin-top: 20px; margin-bottom: 12px; }
        code {
          font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
          font-size: 85%;
          background: #f6f8fa;
          padding: 0.2em 0.4em;
          border-radius: 6px;
        }
        pre {
          background: #f6f8fa;
          padding: 16px;
          border-radius: 6px;
          overflow-x: auto;
          break-inside: avoid;
        }
        pre code { background: none; padding: 0; font-size: 100%; }
        table { border-collapse: collapse; width: 100%; margin: 16px 0; break-inside: avoid; }
        th, td { border: 1px solid #d0d7de; padding: 6px 13px; text-align: left; }
        th { background: #f6f8fa; font-weight: 600; }
        tr { break-inside: avoid; }
        tr:nth-child(even) { background: #f9f9f9; }
        blockquote {
          margin: 0 0 16px 0;
          padding: 0 1em;
          color: #636c76;
          border-left: 0.25em solid #d0d7de;
        }
        hr { border: none; border-top: 1px solid #d0d7de; margin: 24px 0; }
        img, svg { max-width: 100%; height: auto; display: block; margin: 0 auto; }
        a { color: #0969da; text-decoration: none; }
        ul, ol { padding-left: 2em; margin-bottom: 16px; }
        li + li { margin-top: 0.25em; }
        p { margin-top: 0; margin-bottom: 16px; }

      `,
      pdf_options: {
        format: 'A4',
        printBackground: true,
        margin: { top: '40px', right: '40px', bottom: '50px', left: '40px' },
        displayHeaderFooter: true,
        headerTemplate: '<span></span>',
        footerTemplate: `
          <div style="width:100%;font-size:9px;color:#8c959f;padding:0 40px;display:flex;justify-content:space-between">
            <span class="title"></span>
            <span><span class="pageNumber"></span> / <span class="totalPages"></span></span>
          </div>`,
      },
    },
  )

  if (!pdf?.content) {
    process.stderr.write('PDF generation failed: no content returned\n')
    process.exit(1)
  }

  process.stdout.write(pdf.content)
}

main().catch(err => {
  process.stderr.write((err?.message ?? String(err)) + '\n')
  process.exit(1)
})
