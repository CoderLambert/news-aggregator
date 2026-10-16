import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Circle } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useCapabilities } from '@/context/CapabilitiesContext'
import { fetchReadState, updateReadState } from '@/services/api'

const readKey = (viewerId: number, newsId: number) => ['private', 'read-state', { viewerId, newsId }] as const

export default function ReadStateButton({ newsId }: { newsId: number }) {
  const { user } = useAuth()
  const { capabilities } = useCapabilities()
  const client = useQueryClient()
  const enabled = Boolean(user) && capabilities.site_mode === 'full'
  const queryKey = readKey(user?.id ?? 0, newsId)
  const state = useQuery({ queryKey, queryFn: ({ signal }) => fetchReadState(newsId, signal), enabled })
  const mutation = useMutation({
    mutationFn: ({ id, viewerId, isRead, version }: { id: number; viewerId: number; isRead: boolean; version: number }) => updateReadState(id, isRead, version, viewerId),
    onSuccess: (value, input) => client.setQueryData(readKey(input.viewerId, input.id), value),
    onError: (_error, input) => { void client.invalidateQueries({ queryKey: readKey(input.viewerId, input.id) }) },
  })
  if (!enabled) return null
  const isRead = state.data?.is_read ?? false
  return (
    <div className="flex items-center gap-2">
      <button type="button" aria-pressed={isRead} disabled={!state.data || mutation.isPending}
        onClick={() => {
          if (state.data && user) mutation.mutate({ id: newsId, viewerId: user.id, isRead: !state.data.is_read, version: state.data.version })
        }}
        className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-2 text-xs text-muted-foreground hover:text-primary disabled:opacity-50">
        {isRead ? <Check aria-hidden="true" size={16} /> : <Circle aria-hidden="true" size={16} />}
        {state.isPending ? '读取状态…' : isRead ? '已读' : '标为已读'}
      </button>
      {state.isError && <button type="button" onClick={() => void state.refetch()} className="text-xs text-destructive underline">重试读取状态</button>}
      {mutation.isError && <span role="alert" className="text-xs text-destructive">未能保存，请重试。</span>}
    </div>
  )
}
