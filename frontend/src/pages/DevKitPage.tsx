import { useState } from 'react'
import { Info } from 'lucide-react'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Kbd,
  Skeleton,
  Tabs,
  Tooltip,
} from '../components/ui'
import { ConnectionPill, CostMeter, NodeTimeline, SectionCard } from '../components/run'
import type { RunView } from '../lib/runView'
import type { RunStatus } from '../types'

const STATUSES: RunStatus[] = [
  'planning',
  'awaiting_approval',
  'researching',
  'reviewing',
  'writing',
  'done',
  'failed',
]

// Sample RunView for the F11 run-component showcase (mid-run, one section revising).
const SAMPLE_VIEW: RunView = {
  stages: { plan: 'done', approval: 'done', research: 'active', review: 'pending', write: 'pending' },
  sections: [
    {
      id: 's1',
      title: 'Pricing tiers',
      objective: 'Compare per-vector storage costs across managed vendors',
      state: 'revising',
      revision: 1,
      maxRevisions: 2,
      lastReview: { section_id: 's1', verdict: 'revise', score: 0.44, feedback: 'Add the free-tier row.' },
      sourceCount: 5,
    },
    {
      id: 's2',
      title: 'Scale limits',
      objective: 'Document throughput and index-size ceilings',
      state: 'approved',
      revision: 0,
      maxRevisions: 2,
      lastReview: { section_id: 's2', verdict: 'approved', score: 0.87, feedback: '' },
      sourceCount: 3,
    },
  ],
  costTotal: 1.27,
  costByNode: { planner: 0.2, worker: 0.81, reviewer: 0.26 },
  writerDraft: '',
  reportMd: null,
  errorMessage: null,
  status: 'researching',
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="font-mono text-xs uppercase tracking-wider text-text-secondary">
        {title}
      </h2>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </section>
  )
}

// Dev-only visual QA surface for every UI-kit variant (routed at /dev/kit, DEV-gated).
export function DevKitPage() {
  const [tab, setTab] = useState('overview')
  return (
    <div className="mx-auto max-w-4xl space-y-10 px-6 py-10">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-text-primary">
          UI Kit
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          Hand-built components on the Atlas design system (dev only).
        </p>
      </div>

      <Section title="Buttons">
        <Button variant="primary">Primary</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">Danger</Button>
        <Button loading>Loading</Button>
        <Button disabled>Disabled</Button>
        <Button size="sm">Small</Button>
      </Section>

      <Section title="Badges (status)">
        {STATUSES.map((s) => (
          <Badge key={s} status={s} />
        ))}
        <Badge tone="neutral">neutral</Badge>
      </Section>

      <Section title="Card">
        <Card header="Section s1" footer="4 sources" className="w-72">
          <p className="text-sm text-text-secondary">
            Card body content sits on the surface color with a bordered header and footer.
          </p>
        </Card>
      </Section>

      <Section title="Skeleton">
        <div className="w-72 space-y-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      </Section>

      <Section title="Tabs">
        <div className="w-full">
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { value: 'overview', label: 'Overview' },
              { value: 'sources', label: 'Sources' },
              { value: 'cost', label: 'Cost' },
            ]}
          />
          <p className="mt-3 text-sm text-text-secondary">Active tab: {tab}</p>
        </div>
      </Section>

      <Section title="Tooltip + Kbd">
        <Tooltip label="Runs the research agent">
          <span className="inline-flex items-center gap-1.5 text-sm text-text-primary">
            <Info size={14} /> Hover me
          </span>
        </Tooltip>
        <span className="inline-flex items-center gap-1.5 text-sm text-text-secondary">
          <Kbd>⌘</Kbd>
          <Kbd>↵</Kbd> submit
        </span>
      </Section>

      <Section title="Empty state">
        <div className="w-full rounded-card border border-border bg-surface py-10">
          <EmptyState
            title="No runs yet"
            description="Start a run to see it here."
            action={<Button>New Run</Button>}
          />
        </div>
      </Section>

      <Section title="Run components (F11)">
        <div className="flex flex-wrap items-center gap-3">
          <ConnectionPill state="open" />
          <ConnectionPill state="reconnecting" />
          <ConnectionPill state="closed" />
          <CostMeter costTotal={SAMPLE_VIEW.costTotal} costByNode={SAMPLE_VIEW.costByNode} />
        </div>
        <div className="grid w-full gap-4 min-[900px]:grid-cols-[240px_1fr]">
          <Card header="Progress">
            <NodeTimeline view={SAMPLE_VIEW} />
          </Card>
          <div className="grid gap-4 sm:grid-cols-2">
            {SAMPLE_VIEW.sections.map((s) => (
              <SectionCard key={s.id} section={s} />
            ))}
          </div>
        </div>
      </Section>
    </div>
  )
}
