import { History, Plus, type LucideIcon } from 'lucide-react'
import { NavLink, Outlet, Route, Routes } from 'react-router'
import { cn } from './lib/cn'
import { Button, EmptyState } from './components/ui'
import { NewRunPage } from './pages/NewRunPage'
import { RunPage } from './pages/RunPage'
import { ReportPage } from './pages/ReportPage'
import { SectionDraftPage } from './pages/SectionDraftPage'
import { HistoryPage } from './pages/HistoryPage'
import { DevKitPage } from './pages/DevKitPage'

const NAV: { to: string; label: string; icon: LucideIcon }[] = [
  { to: '/', label: 'New Run', icon: Plus },
  { to: '/history', label: 'History', icon: History },
]

function AppShell() {
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
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-control px-3 py-2 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent',
                  isActive
                    ? 'bg-raised text-text-primary'
                    : 'text-text-secondary hover:bg-raised/60 hover:text-text-primary',
                )
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}

function NotFound() {
  return (
    <div className="flex min-h-full items-center justify-center px-6 py-16">
      <EmptyState
        title="Page not found"
        description="The page you're looking for doesn't exist."
        action={
          <NavLink to="/">
            <Button>Back to New Run</Button>
          </NavLink>
        }
      />
    </div>
  )
}

function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<NewRunPage />} />
        <Route path="/runs/:id" element={<RunPage />} />
        <Route path="/runs/:id/report" element={<ReportPage />} />
        <Route path="/runs/:id/sections/:sectionId" element={<SectionDraftPage />} />
        <Route path="/history" element={<HistoryPage />} />
        {import.meta.env.DEV && <Route path="/dev/kit" element={<DevKitPage />} />}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

export default App
