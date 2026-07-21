import { History, Plus, type LucideIcon } from 'lucide-react'
import { useState } from 'react'

type NavKey = 'new' | 'history'

const NAV: { key: NavKey; label: string; icon: LucideIcon }[] = [
  { key: 'new', label: 'New Run', icon: Plus },
  { key: 'history', label: 'History', icon: History },
]

function App() {
  const [active, setActive] = useState<NavKey>('new')

  return (
    <div className="flex h-screen bg-background text-text-primary">
      <aside className="flex w-60 flex-col border-r border-border bg-surface">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <span className="grid h-7 w-7 place-items-center rounded-control bg-accent/15 font-mono text-sm font-semibold text-accent">
            A
          </span>
          <span className="text-lg font-semibold tracking-tight">Atlas</span>
        </div>
        <nav className="flex flex-col gap-1 px-3">
          {NAV.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setActive(key)}
              aria-current={active === key ? 'page' : undefined}
              className={`flex items-center gap-3 rounded-control px-3 py-2 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent ${
                active === key
                  ? 'bg-raised text-text-primary'
                  : 'text-text-secondary hover:bg-raised/60 hover:text-text-primary'
              }`}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </nav>
      </aside>

      <main className="flex flex-1 items-center justify-center p-8">
        <div className="max-w-sm text-center">
          <h1 className="text-base font-medium text-text-primary">
            {active === 'new' ? 'Start a new research run' : 'No runs yet'}
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">
            {active === 'new'
              ? 'Submit a topic and Atlas will plan, research, and synthesize a cited report.'
              : 'Completed and in-progress runs will appear here.'}
          </p>
          <button
            type="button"
            onClick={() => setActive('new')}
            className="mt-5 inline-flex items-center gap-2 rounded-control bg-accent px-4 py-2 text-sm font-medium text-background outline-none transition-colors hover:bg-accent/90 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <Plus size={16} />
            New Run
          </button>
        </div>
      </main>
    </div>
  )
}

export default App
