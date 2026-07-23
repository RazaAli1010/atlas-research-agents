// SourceList (F12): the report's global deduped sources, rendered structured so citation
// superscripts ([n] → #source-n) can anchor-jump here. Source index n (1-based) matches the
// report's [n] markers because the backend derives `RunDetail.sources` from the same writer
// merge that numbers the markers.
import { useState } from 'react'
import { Calculator, Globe } from 'lucide-react'
import type { Source, ToolName } from '../../types'
import { Badge, type Tone } from '../ui'

const TOOL_BADGE: Record<ToolName, { label: string; tone: Tone }> = {
  web_search: { label: 'web', tone: 'accent' },
  rag: { label: 'rag', tone: 'neutral' },
  calculator: { label: 'calc', tone: 'neutral' },
}

function hostnameOf(url: string): string | null {
  try {
    return new URL(url).hostname
  } catch {
    return null
  }
}

function Favicon({ host }: { host: string }) {
  const [failed, setFailed] = useState(false)
  if (failed) return <Globe size={16} className="text-text-secondary" aria-hidden />
  return (
    <img
      src={`https://www.google.com/s2/favicons?domain=${host}&sz=32`}
      alt=""
      width={16}
      height={16}
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className="rounded-sm"
    />
  )
}

function SourceRow({ source, n }: { source: Source; n: number }) {
  const host = source.url ? hostnameOf(source.url) : null
  const badge = TOOL_BADGE[source.tool]
  const title = source.title || host || source.snippet || source.url

  return (
    <li
      id={`source-${n}`}
      className="flex scroll-mt-20 gap-3 rounded-control px-2 py-2 target:bg-raised/60"
    >
      <span className="mt-0.5 w-5 shrink-0 text-right font-mono text-xs text-text-secondary">
        {n}
      </span>
      <span className="mt-0.5 shrink-0">
        {host ? <Favicon host={host} /> : <Calculator size={16} className="text-text-secondary" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          {source.url ? (
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="truncate text-sm text-text-primary underline-offset-2 outline-none hover:text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent"
            >
              {title}
            </a>
          ) : (
            <span className="truncate text-sm text-text-primary">{title}</span>
          )}
          <Badge tone={badge.tone}>{badge.label}</Badge>
        </div>
        {host && <p className="truncate font-mono text-xs text-text-secondary">{host}</p>}
      </div>
    </li>
  )
}

export interface SourceListProps {
  sources: Source[]
}

export function SourceList({ sources }: SourceListProps) {
  if (sources.length === 0) {
    return <p className="text-sm text-text-secondary">No sources were cited.</p>
  }
  return (
    <ol className="space-y-1">
      {sources.map((source, i) => (
        <SourceRow key={i} source={source} n={i + 1} />
      ))}
    </ol>
  )
}
