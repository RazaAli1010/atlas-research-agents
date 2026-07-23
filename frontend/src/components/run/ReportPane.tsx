// Writer output pane (F11): streams raw token deltas as a monospace draft, then swaps to
// basic rendered markdown on done. The polished ReportViewer + SourceList are F12.
import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export interface ReportPaneProps {
  writerDraft: string
  reportMd: string | null
}

export function ReportPane({ writerDraft, reportMd }: ReportPaneProps) {
  const draftRef = useRef<HTMLPreElement>(null)

  // Keep the streaming draft pinned to the newest tokens.
  useEffect(() => {
    const el = draftRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [writerDraft])

  const hasDraft = writerDraft.length > 0

  return (
    // Reserved min-height so the streaming→rendered swap doesn't shift the page.
    <div className="min-h-40">
      {reportMd !== null ? (
        <div className="prose-atlas max-w-none text-sm text-text-primary">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{reportMd}</ReactMarkdown>
        </div>
      ) : hasDraft ? (
        <pre
          ref={draftRef}
          className="max-h-[28rem] overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-text-secondary"
        >
          {writerDraft}
        </pre>
      ) : (
        <p className="text-sm text-text-secondary">
          The final report will stream here once research is approved and the writer runs.
        </p>
      )}
    </div>
  )
}
