// TanStack Query v5 hooks (object-form API only) over the typed client.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ResumeAction } from '../types'
import { api } from './client'

export const runKeys = {
  all: ['runs'] as const,
  detail: (id: string) => ['runs', id] as const,
}

export function useRuns() {
  return useQuery({ queryKey: runKeys.all, queryFn: api.listRuns })
}

export function useRun(id: string) {
  return useQuery({
    queryKey: runKeys.detail(id),
    queryFn: () => api.getRun(id),
    enabled: !!id,
  })
}

export function useCreateRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.createRun,
    onSuccess: () => qc.invalidateQueries({ queryKey: runKeys.all }),
  })
}

export function useResumeRun(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ResumeAction) => api.resumeRun(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: runKeys.detail(id) })
      qc.invalidateQueries({ queryKey: runKeys.all })
    },
  })
}
