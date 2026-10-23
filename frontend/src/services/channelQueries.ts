import { useLayoutEffect, useRef } from 'react'
import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { useCapability } from '@/context/CapabilitiesContext'
import { fetchSources, fetchChannelSubscriptions, fetchChannelGroups, fetchChannelGroupRoots, fetchNewsPreferences, saveNewsPreferences } from '@/services/api'
import { parseChannels, parseSubscriptions, parseGroups, parseRoots, parseNewsPreference, validateHierarchy } from '@/types/channels'
import { newsKeys } from '@/services/newsQueries'

export const channelKeys = {
  all: ['channels'] as const,
  personal: (viewer: number | string) => ['channels', 'personal', viewer] as const,
  subscriptions: (viewer: number | string) => ['channels', 'personal', viewer, 'subscriptions'] as const,
  roots: (viewer: number | string) => ['channels', 'personal', viewer, 'roots'] as const,
  groups: (viewer: number | string) => ['channels', 'personal', viewer, 'groups'] as const,
  preferences: (viewer: number | string) => ['channels', 'personal', viewer, 'preferences'] as const,
  directories: ['channels', 'directory'] as const,
  directory: (viewer: number | string, purpose: 'subscribe' | 'history') => ['channels', 'directory', { viewer, purpose }] as const,
}
export const channelDirectoryOptions = (viewer: number | string, purpose: 'subscribe' | 'history' = 'subscribe') => queryOptions({
  queryKey: channelKeys.directory(viewer, purpose),
  queryFn: async ({ signal }) => parseChannels(await fetchSources(signal, purpose)),
})
export function useChannelConfig() {
  const { user, loading } = useAuth()
  const accounts = useCapability('accounts').enabled
  const viewer = user?.id ?? 'anonymous'
  const enabled = !loading && accounts && !!user
  const subscriptions = useQuery({ queryKey: channelKeys.subscriptions(viewer), enabled,
    queryFn: async ({ signal }) => parseSubscriptions(await fetchChannelSubscriptions(signal)) })
  const roots = useQuery({ queryKey: channelKeys.roots(viewer), enabled,
    queryFn: async ({ signal }) => parseRoots(await fetchChannelGroupRoots(signal)) })
  const groups = useQuery({ queryKey: channelKeys.groups(viewer), enabled,
    queryFn: async ({ signal }) => parseGroups(await fetchChannelGroups(signal)) })
  const topologyValid = !!roots.data && !!groups.data && validateHierarchy(roots.data, groups.data)
  return { subscriptions, roots, groups, enabled, viewer, accounts,
    ready: !enabled || (subscriptions.isSuccess && roots.isSuccess && groups.isSuccess && topologyValid),
    error: enabled && (subscriptions.isError || roots.isError || groups.isError ||
      (roots.isSuccess && groups.isSuccess && !topologyValid)),
    retry: () => Promise.all([subscriptions.refetch(), roots.refetch(), groups.refetch()]) }
}
export function useNewsPreference(enabled: boolean, viewer: number | string) {
  return useQuery({ queryKey: channelKeys.preferences(viewer), enabled,
    queryFn: async ({ signal }) => parseNewsPreference(await fetchNewsPreferences(signal)) })
}
export function useSaveNewsPreference(viewer: number | string) {
  const client = useQueryClient()
  const currentViewer = useRef<number | string | null>(viewer)
  useLayoutEffect(() => {
    currentViewer.current = viewer
    return () => { currentViewer.current = null }
  }, [viewer])
  return useMutation({ mutationFn: (payload: import('@/types/channels').NewsPreference) => {
    if (currentViewer.current !== viewer || viewer === 'anonymous') throw new Error('账号已切换，请重试。')
    return saveNewsPreferences(payload)
  }, scope: { id: `news-preference-${viewer}` },
    onSuccess: value => {
      if (currentViewer.current === viewer) client.setQueryData(channelKeys.preferences(viewer), parseNewsPreference(value))
    } })
}
export function useChannelMutation() {
  const { user } = useAuth()
  const viewer = user?.id ?? 'anonymous'
  const client = useQueryClient()
  const currentViewer = useRef<number | string | null>(viewer)
  useLayoutEffect(() => {
    currentViewer.current = viewer
    return () => { currentViewer.current = null }
  }, [viewer])
  return useMutation({ mutationFn: (perform: () => Promise<unknown>) => {
    if (currentViewer.current !== viewer || viewer === 'anonymous') throw new Error('账号已切换，请重试。')
    return perform()
  }, scope: { id: `channels-${viewer}` },
    onSuccess: async () => {
      if (currentViewer.current !== viewer) return
      await client.cancelQueries({ queryKey: newsKeys.lists() })
      await Promise.all([
        client.invalidateQueries({ queryKey: channelKeys.personal(viewer) }),
        client.invalidateQueries({ queryKey: channelKeys.directories }),
        client.invalidateQueries({ queryKey: newsKeys.sources('zh', viewer) }),
        client.invalidateQueries({ queryKey: newsKeys.sources('en', viewer) }),
        client.resetQueries({ queryKey: newsKeys.lists() }),
      ])
    } })
}
