import { useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router'
import { ArrowRight } from 'lucide-react'
import { Button, Kbd } from '../components/ui'
import { useCreateRun } from '../api/queries'
import { ApiError } from '../api/client'

const EXAMPLES = [
  'Compare vector database pricing for a seed-stage startup',
  'State of small open-weight LLMs for on-device inference in 2026',
  'Managed Postgres vs. self-hosted for a 3-person team',
]

export function NewRunPage() {
  const [topic, setTopic] = useState('')
  const navigate = useNavigate()
  const createRun = useCreateRun()

  const trimmed = topic.trim()
  const canSubmit = trimmed.length > 0 && !createRun.isPending

  async function submit() {
    if (!canSubmit) return
    try {
      const data = await createRun.mutateAsync(trimmed)
      navigate(`/runs/${data.run_id}`)
    } catch {
      /* error surfaced inline below via createRun.error */
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      void submit()
    }
  }

  const errorMessage =
    createRun.error instanceof ApiError
      ? createRun.error.message
      : createRun.error
        ? 'Something went wrong. Please try again.'
        : null

  return (
    <div className="mx-auto flex min-h-full max-w-2xl flex-col justify-center px-6 py-16">
      <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
        What should Atlas research?
      </h1>
      <p className="mt-2 text-sm text-text-secondary">
        Atlas will plan the work, pause for your approval, then research and synthesize a
        cited report.
      </p>

      <textarea
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
        onKeyDown={onKeyDown}
        rows={4}
        autoFocus
        placeholder="e.g. Compare vector database pricing for a seed-stage startup"
        className="mt-6 w-full resize-none rounded-card border border-border bg-surface px-4 py-3 text-sm text-text-primary outline-none placeholder:text-text-secondary/60 focus-visible:ring-2 focus-visible:ring-accent"
      />

      <div className="mt-3 flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => setTopic(ex)}
            className="rounded-full border border-border bg-surface px-3 py-1 text-left text-xs text-text-secondary outline-none transition-colors hover:border-accent/50 hover:text-text-primary focus-visible:ring-2 focus-visible:ring-accent"
          >
            {ex}
          </button>
        ))}
      </div>

      {errorMessage && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {errorMessage}
        </p>
      )}

      <div className="mt-6 flex items-center justify-between">
        <span className="text-xs text-text-secondary">
          typical run <span className="font-mono text-text-primary">&lt; $0.50</span>
        </span>
        <div className="flex items-center gap-3">
          <span className="hidden items-center gap-1.5 text-xs text-text-secondary sm:flex">
            <Kbd>⌘</Kbd>
            <Kbd>↵</Kbd>
            to start
          </span>
          <Button onClick={() => void submit()} disabled={!canSubmit} loading={createRun.isPending}>
            Start research
            <ArrowRight size={16} />
          </Button>
        </div>
      </div>
    </div>
  )
}
