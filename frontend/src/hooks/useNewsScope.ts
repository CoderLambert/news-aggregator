import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import type { SetURLSearchParams } from 'react-router-dom'
import { isRecord } from '@/types/news'
import { useChannelConfig, useNewsPreference, useSaveNewsPreference } from '@/services/channelQueries'
import { newsScopes } from '@/types/channels'
import type { NewsScope } from '@/types/channels'

export function useNewsScope(params: URLSearchParams, setParams: SetURLSearchParams, migrating: boolean) {
  const config = useChannelConfig()
  const preference = useNewsPreference(config.enabled, config.viewer)
  const save = useSaveNewsPreference(config.viewer)
  const { mutate } = save
  const location = useLocation()
  const notice = isRecord(location.state) && location.state.scopeNotice === 'group-unavailable' ? '该分组已删除或不可访问，已返回我的订阅。' : ''
  const raw = params.get('scope')
  const scope: NewsScope = config.accounts && newsScopes.includes(raw as NewsScope) ? raw as NewsScope : 'all'
  const groupId = scope === 'group' ? Number(params.get('group_id')) : undefined
  const validGroup = scope !== 'group' || config.groups.data?.some(g => g.id === groupId)
  const invalidScope = config.accounts && raw !== null && !newsScopes.includes(raw as NewsScope)
  const needsLogin = config.accounts && !config.enabled && scope !== 'all'
  const configError = (scope !== 'all' && config.error) || (config.enabled && raw === null && preference.isError)
  const ready = !migrating && !invalidScope && !needsLogin && (!config.enabled ||
    (raw !== null && (scope === 'all' || (config.ready && validGroup))))
  const lastSaved = useRef('')

  useEffect(() => {
    if (migrating) return
    if (!config.accounts && (params.has('scope') || params.has('group_id'))) {
      const next = new URLSearchParams(params)
      next.delete('scope'); next.delete('group_id')
      if (raw !== null && raw !== 'all') { next.delete('source'); next.delete('page') }
      setParams(next, { replace: true })
      return
    }
    if (!config.enabled) return
    if (raw === null) {
      if (!preference.isSuccess) return
      const next = new URLSearchParams(params)
      next.set('scope', preference.data.scope)
      if (preference.data.group_id !== null) next.set('group_id', String(preference.data.group_id))
      else next.delete('group_id')
      setParams(next, { replace: true })
    } else if (scope === 'group' && config.ready && !validGroup) {
      const next = new URLSearchParams(params)
      next.set('scope', 'subscribed'); next.delete('group_id'); next.delete('source'); next.delete('page')
      setParams(next, { replace: true, state: { scopeNotice: 'group-unavailable' } })
    }
  }, [config.accounts, config.enabled, config.ready, migrating, params, preference.data, preference.isSuccess, raw, scope, setParams, validGroup])

  useEffect(() => {
    if (!ready || !config.enabled || configError || !preference.isSuccess) return
    const signature = `${config.viewer}:${scope}:${groupId ?? ''}`
    if (lastSaved.current === signature) return
    lastSaved.current = signature
    if (preference.data?.scope === scope && preference.data.group_id === (groupId ?? null)) return
    mutate({ scope, group_id: groupId ?? null })
  }, [config.enabled, config.viewer, configError, groupId, mutate, preference.data, preference.isSuccess, ready, scope])

  const subscriptionIds = (config.subscriptions.data ?? []).filter(s => scope !== 'ungrouped' || s.group_ids.length === 0).map(s => s.source_id)
  const sourceIds = scope === 'all' ? null : scope === 'group'
    ? config.groups.data?.find(g => g.id === groupId)?.source_ids ?? [] : subscriptionIds

  return { ...config, scope, groupId, sourceIds, ready: Boolean(ready), configError, needsLogin, invalidScope, notice,
    saveError: save.isError,
    retrySave: () => mutate({ scope, group_id: groupId ?? null }),
    retry: () => Promise.all([config.retry(), preference.refetch()]),
    select: (value: string) => {
      const next = new URLSearchParams(params)
      const [nextScope, id] = value.split(':')
      next.set('scope', nextScope)
      if (id) next.set('group_id', id); else next.delete('group_id')
      next.delete('source'); next.delete('page')
      setParams(next)
    } }
}
