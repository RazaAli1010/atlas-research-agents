// PlanApprovalPanel (F12): the human-in-the-loop gate. Renders the planner's proposed plan
// as editable cards and resumes the interrupted run with approve / edit. Edits actually
// change the run — a deleted section produces no worker downstream (fan_out keys workers by
// SectionPlan.id, so we renumber ids on submit).
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, Plus, Trash2, X } from 'lucide-react'
import type { ResumeAction, SectionPlan } from '../../types'
import { ApiError } from '../../api/client'
import { runKeys, useResumeRun } from '../../api/queries'
import { Badge, Button, Card } from '../ui'

// Mirrors backend MAX_SECTIONS in app/graph/state.py; the server clamps/validates too — this
// cap is UX only.
const MAX_SECTIONS = 6

function clone(s: SectionPlan): SectionPlan {
  return { ...s, suggested_queries: [...s.suggested_queries] }
}

function sameShape(a: SectionPlan[], b: SectionPlan[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

// Reassign ids to s1..sN in current order so every section is unique (approval_gate does not
// renumber edited plans) and the timeline maps node_started{worker, section_id} cleanly.
function normalize(sections: SectionPlan[]): SectionPlan[] {
  return sections.map((s, i) => ({ ...s, id: `s${i + 1}` }))
}

interface SectionEditorProps {
  section: SectionPlan
  index: number
  total: number
  disabled: boolean
  onChange: (patch: Partial<SectionPlan>) => void
  onMove: (dir: -1 | 1) => void
  onRemove: () => void
}

function SectionEditor({
  section,
  index,
  total,
  disabled,
  onChange,
  onMove,
  onRemove,
}: SectionEditorProps) {
  const [query, setQuery] = useState('')

  function addQuery() {
    const q = query.trim()
    if (!q || section.suggested_queries.includes(q)) {
      setQuery('')
      return
    }
    onChange({ suggested_queries: [...section.suggested_queries, q] })
    setQuery('')
  }

  const inputCls =
    'w-full rounded-control border border-border bg-raised px-3 py-2 text-sm text-text-primary ' +
    'outline-none placeholder:text-text-secondary focus-visible:ring-2 focus-visible:ring-accent ' +
    'disabled:opacity-50'

  return (
    <Card>
      <div className="flex items-start gap-3">
        <span className="mt-2 font-mono text-xs text-text-secondary">{index + 1}</span>
        <div className="min-w-0 flex-1 space-y-3">
          <input
            aria-label={`Section ${index + 1} title`}
            value={section.title}
            disabled={disabled}
            onChange={(e) => onChange({ title: e.target.value })}
            placeholder="Section title"
            className={inputCls}
          />
          <textarea
            aria-label={`Section ${index + 1} objective`}
            value={section.objective}
            disabled={disabled}
            onChange={(e) => onChange({ objective: e.target.value })}
            placeholder="What should this section answer?"
            rows={2}
            className={`${inputCls} resize-y`}
          />
          <div>
            <div className="flex flex-wrap gap-1.5">
              {section.suggested_queries.map((q, qi) => (
                <span
                  key={qi}
                  className="inline-flex items-center gap-1 rounded-full bg-raised px-2.5 py-0.5 text-xs text-text-secondary"
                >
                  {q}
                  <button
                    type="button"
                    aria-label={`Remove query ${q}`}
                    disabled={disabled}
                    onClick={() =>
                      onChange({
                        suggested_queries: section.suggested_queries.filter((_, k) => k !== qi),
                      })
                    }
                    className="rounded outline-none hover:text-danger focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
            <input
              aria-label={`Add suggested query to section ${index + 1}`}
              value={query}
              disabled={disabled}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  addQuery()
                }
              }}
              placeholder="Add a query, press Enter"
              className={`${inputCls} mt-1.5`}
            />
          </div>
        </div>
        <div className="flex shrink-0 flex-col gap-1">
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Move section ${index + 1} up`}
            disabled={disabled || index === 0}
            onClick={() => onMove(-1)}
          >
            <ChevronUp size={14} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Move section ${index + 1} down`}
            disabled={disabled || index === total - 1}
            onClick={() => onMove(1)}
          >
            <ChevronDown size={14} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Delete section ${index + 1}`}
            disabled={disabled}
            onClick={onRemove}
            className="hover:text-danger"
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </div>
    </Card>
  )
}

export interface PlanApprovalPanelProps {
  runId: string
  proposedPlan: SectionPlan[]
}

export function PlanApprovalPanel({ runId, proposedPlan }: PlanApprovalPanelProps) {
  const [sections, setSections] = useState<SectionPlan[]>(() => proposedPlan.map(clone))
  const [error, setError] = useState<string | null>(null)
  const resume = useResumeRun(runId)
  const qc = useQueryClient()

  // The proposed plan arrives via the `interrupt` SSE payload, which can land *after* this
  // panel mounts (status flips to awaiting_approval first). A one-shot useState initializer
  // would capture an empty plan and never recover, leaving the plan invisible and the submit
  // button stuck disabled. Re-seed `sections` from `proposedPlan` while the panel is still
  // pristine — i.e. the user hasn't edited away from the plan we last seeded. Once they type,
  // `sections` diverges from the last seed and we stop overwriting their edits.
  const seededRef = useRef<SectionPlan[]>(proposedPlan)
  useEffect(() => {
    const pristine = sections.length === 0 || sameShape(sections, seededRef.current)
    if (pristine && !sameShape(sections, proposedPlan)) {
      setSections(proposedPlan.map(clone))
    }
    seededRef.current = proposedPlan
  }, [proposedPlan, sections])

  const pending = resume.isPending
  const dirty = !sameShape(sections, proposedPlan)
  const hasBlankTitle = sections.some((s) => s.title.trim() === '')
  const canSubmit = sections.length > 0 && !hasBlankTitle

  function patch(i: number, p: Partial<SectionPlan>) {
    setSections((prev) => prev.map((s, k) => (k === i ? { ...s, ...p } : s)))
  }
  function move(i: number, dir: -1 | 1) {
    setSections((prev) => {
      const j = i + dir
      if (j < 0 || j >= prev.length) return prev
      const next = [...prev]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }
  function remove(i: number) {
    setSections((prev) => prev.filter((_, k) => k !== i))
  }
  function addSection() {
    setSections((prev) =>
      prev.length >= MAX_SECTIONS
        ? prev
        : [...prev, { id: '', title: '', objective: '', suggested_queries: [] }],
    )
  }

  function submit(body: ResumeAction) {
    setError(null)
    resume.mutate(body, {
      onError: (err) => {
        if (err instanceof ApiError && err.status === 409) {
          setError('This run was already resumed.')
          qc.invalidateQueries({ queryKey: runKeys.detail(runId) })
        } else {
          setError(err instanceof Error ? err.message : 'Failed to resume run.')
        }
      },
    })
  }

  return (
    <Card header="Review the research plan">
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Badge tone="warn">Awaiting approval</Badge>
          <p className="text-sm text-text-secondary">
            Atlas paused for your review. Edit the plan below, then approve to start research.
          </p>
        </div>

        <div className="space-y-3">
          {sections.map((s, i) => (
            <SectionEditor
              key={i}
              section={s}
              index={i}
              total={sections.length}
              disabled={pending}
              onChange={(p) => patch(i, p)}
              onMove={(dir) => move(i, dir)}
              onRemove={() => remove(i)}
            />
          ))}
        </div>

        <div className="flex items-center justify-between">
          <Button
            variant="secondary"
            size="sm"
            onClick={addSection}
            disabled={pending || sections.length >= MAX_SECTIONS}
          >
            <Plus size={14} />
            Add section
          </Button>
          <span className="font-mono text-xs text-text-secondary">
            {sections.length}/{MAX_SECTIONS} sections
          </span>
        </div>

        {error && <p className="text-sm text-danger">{error}</p>}

        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
          {dirty ? (
            <>
              <Button
                variant="primary"
                loading={pending}
                disabled={!canSubmit || pending}
                onClick={() => submit({ action: 'edit', plan: normalize(sections) })}
              >
                Approve with edits
              </Button>
              <Button
                variant="ghost"
                disabled={pending}
                onClick={() => submit({ action: 'approve' })}
              >
                Discard edits & approve original
              </Button>
            </>
          ) : (
            <Button
              variant="primary"
              loading={pending}
              disabled={!canSubmit || pending}
              onClick={() => submit({ action: 'approve' })}
            >
              Approve plan
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}
