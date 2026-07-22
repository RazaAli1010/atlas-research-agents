import { useNavigate } from 'react-router'
import { Plus } from 'lucide-react'
import { Button, EmptyState } from '../components/ui'

export function HistoryPage() {
  const navigate = useNavigate()
  return (
    <div className="mx-auto flex min-h-full max-w-4xl items-center justify-center px-6 py-16">
      <EmptyState
        title="No runs yet"
        description="Runs you start will appear here with their status and cost. The full history list arrives in a later milestone."
        action={
          <Button onClick={() => navigate('/')}>
            <Plus size={16} />
            New Run
          </Button>
        }
      />
    </div>
  )
}
