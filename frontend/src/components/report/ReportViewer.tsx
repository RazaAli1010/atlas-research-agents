// ReportViewer (F12): the polished final report. Renders the report body markdown with
// citation markers ([n]) turned into accent superscript links that jump to a structured
// SourceList, plus copy / download-.md / open-trace actions. Replaces F11's basic ReportPane
// output for the `done` state.
import { useState, type ComponentPropsWithoutRef } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, Copy, Download, ExternalLink } from 'lucide-react'
import type { Source } from '../../types'
import { api } from '../../api/client'
import { LANGSMITH_HOME, langsmithTraceUrl } from '../../lib/langsmith'
import { linkifyCitations, splitReportBody } from '../../lib/citations'
import { Button } from '../ui'
import { SourceList } from './SourceList'

export interface ReportViewerProps {
  reportMd: string
  sources: Source[]
  runId: string
  traceId: string | null
}

// Anchor renderer: citation links (#source-n) become superscripts; everything else stays a
// normal link (external links open in a new tab). Anchor to a missing source is a harmless
// no-op — we still render the superscript.
const mdComponents: Components = {
  a({ href, children, ...props }: ComponentPropsWithoutRef<'a'>) {
    if (href?.startsWith('#source-')) {
      return (
        <sup>
          <a href={href} {...props}>
            {children}
          </a>
        </sup>
      )
    }
    const external = href?.startsWith('http')
    return (
      <a href={href} {...(external ? { target: '_blank', rel: 'noreferrer' } : {})} {...props}>
        {children}
      </a>
    )
  },
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <Button variant="secondary" size="sm" onClick={copy} aria-label="Copy report markdown">
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? 'Copied' : 'Copy'}
    </Button>
  )
}

export function ReportViewer({ reportMd, sources, runId, traceId }: ReportViewerProps) {
  const { body } = splitReportBody(reportMd)
  const traceUrl = langsmithTraceUrl(traceId) ?? LANGSMITH_HOME

  const actionLink =
    'inline-flex h-8 items-center gap-1.5 rounded-control border border-border bg-raised px-3 text-xs ' +
    'font-medium text-text-primary outline-none transition-colors hover:bg-raised/70 ' +
    'focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:ring-accent'

  return (
    <div className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-end gap-2 border-b border-border px-4 py-3">
        <CopyButton text={reportMd} />
        <a href={api.reportUrl(runId)} download className={actionLink}>
          <Download size={14} />
          Download .md
        </a>
        <a href={traceUrl} target="_blank" rel="noreferrer" className={actionLink}>
          <ExternalLink size={14} />
          Open trace
        </a>
      </div>

      <div className="px-5 py-5">
        <div className="prose-atlas max-w-[68ch]">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {linkifyCitations(body)}
          </ReactMarkdown>
        </div>

        <div className="mt-8 border-t border-border pt-5">
          <h2 className="mb-3 text-sm font-semibold text-text-primary">Sources</h2>
          <SourceList sources={sources} />
        </div>
      </div>
    </div>
  )
}
