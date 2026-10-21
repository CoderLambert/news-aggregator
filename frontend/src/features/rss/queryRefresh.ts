import type { QueryClient } from '@tanstack/react-query'
import { newsKeys } from '@/services/newsQueries'
import { channelKeys } from '@/services/channelQueries'
import { workspaceKeys } from '@/services/workspaceApi'

/** Invalidate only this viewer; never discard another account's retained state. */
export function refreshRssViews(client: QueryClient, viewer: number) {
  return Promise.all([
    client.invalidateQueries({ queryKey: ['private', 'rss-directory', viewer] }),
    client.invalidateQueries({ queryKey: channelKeys.personal(viewer) }),
    client.invalidateQueries({ queryKey: channelKeys.directory(viewer, 'history') }),
    client.invalidateQueries({ queryKey: channelKeys.directory(viewer, 'subscribe') }),
    client.invalidateQueries({ queryKey: workspaceKeys.viewerCatalog(viewer, 'history') }),
    client.invalidateQueries({ queryKey: workspaceKeys.viewerCatalog(viewer, 'subscribe') }),
    client.invalidateQueries({ queryKey: newsKeys.sources('zh', viewer) }),
    client.invalidateQueries({ queryKey: newsKeys.sources('en', viewer) }),
    client.invalidateQueries({ queryKey: newsKeys.viewerLists(viewer) }),
  ])
}
