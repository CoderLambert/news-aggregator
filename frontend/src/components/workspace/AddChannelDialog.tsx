import { useAuth } from '@/context/AuthContext'
import { useChannelConfig } from '@/services/channelQueries'
import type { Topic } from '@/services/workspaceApi'
import DiscoverDialog from '@/features/rss/DiscoverDialog'

export default function AddChannelDialog({ onClose, onDone }: { topics: Topic[]; onClose: () => void; onDone: () => void }) {
  const { user } = useAuth()
  const config = useChannelConfig()
  if (!user) return null
  return <DiscoverDialog key={user.id} viewer={user.id} roots={config.roots.data ?? []} groups={config.groups.data ?? []} onClose={onClose} onDone={onDone} />
}
