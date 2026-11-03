import type { ChannelProfile } from '@/services/workspaceApi'

export function canRecommendChannel(source: ChannelProfile) {
  return source.publication === 'personal' && source.collection_owner === 'miniflux'
    && source.subscription_status === 'active'
}
