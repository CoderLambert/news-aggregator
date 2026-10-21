import { useQuery } from '@tanstack/react-query'
import { listAITaskPreferences, type AITaskKind } from '@/services/aiConnectionsApi'

/** Resolve saved task/default preferences only; never choose another model. */
export function useDefaultAIModel(viewer: number | null, taskKind: AITaskKind, enabled = true) {
  const query = useQuery({
    queryKey: ['ai-task-preferences', viewer ?? 'anonymous'],
    queryFn: ({ signal }) => listAITaskPreferences(signal),
    enabled: viewer !== null && enabled,
    retry: false,
  })
  const task = query.data?.preferences.find(item => item.task_kind === taskKind)
  const selection = query.isError ? null : task?.selection_state === 'available' ? task
    : task?.selection_state === 'inherit_default'
      ? query.data?.preferences.find(item => item.task_kind === 'default' && item.selection_state === 'available') ?? null
      : null
  return { ...query, selection }
}
