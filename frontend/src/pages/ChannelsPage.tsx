import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { channelDirectoryOptions, useChannelConfig, useChannelMutation } from '@/services/channelQueries'
import { changeChannelSubscriptions, createChannelGroup, updateChannelGroup, deleteChannelGroup } from '@/services/api'
import { isRecord } from '@/types/news'
import type { ChannelGroup } from '@/types/channels'
import { Button } from '@/components/ui/button'
import RegionFilter from '@/components/RegionFilter'
import LoadingSpinner from '@/components/LoadingSpinner'
import AuthModal from '@/components/AuthModal'
import ChannelConfirmationDialog from '@/components/ChannelConfirmationDialog'

function errorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = error.response as { data?: unknown }
    if (response.data && typeof response.data === 'object') {
      return Object.values(response.data).flat().map(String).join(' ')
    }
  }
  return '操作失败，请重试。'
}
const control = 'min-h-11 rounded-lg border border-border bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-primary'

export default function ChannelsPage() {
  const { user } = useAuth()
  return <ChannelManager key={user?.id ?? 'anonymous'} />
}

function ChannelManager() {
  const { user, loading } = useAuth()
  const location = useLocation()
  const returnTo = isRecord(location.state) && typeof location.state.newsReturnTo === 'string' && /^\/(?:\?|$)/.test(location.state.newsReturnTo) ? location.state.newsReturnTo : '/'
  const config = useChannelConfig()
  const directory = useQuery(channelDirectoryOptions())
  const mutation = useChannelMutation()
  const [tab, setTab] = useState<'all' | 'subscribed' | 'groups'>('all')
  const [search, setSearch] = useState('')
  const [directoryParams, setDirectoryParams] = useSearchParams()
  const invalidRegion = directoryParams.has('region') && !['domestic', 'international'].includes(directoryParams.get('region') ?? '')
  const region = directoryParams.get('region') === 'domestic' ? 'domestic' : directoryParams.get('region') === 'international' ? 'international' : 'all'
  function setRegion(value: import('@/types/news').SourceRegion | 'all') {
    const next = new URLSearchParams(directoryParams)
    if (value === 'all') next.delete('region'); else next.set('region', value)
    setDirectoryParams(next, { state: location.state })
  }
  const [language, setLanguage] = useState('')
  const [sourceType, setSourceType] = useState('')
  const [selected, setSelected] = useState<number[]>([])
  const [groupId, setGroupId] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [login, setLogin] = useState(false)
  const [confirmation, setConfirmation] = useState<{ description: string; perform: () => Promise<unknown> } | null>(null)
  const groups = config.groups.data ?? []
  const subscriptionMap = new Map((config.subscriptions.data ?? []).map(s => [s.source_id, s]))
  const currentGroup = groups.find(g => g.id === groupId) ?? groups[0]
  const writable = config.enabled && config.ready && !config.error && !mutation.isPending
  const visible = (directory.data ?? []).filter(c => !invalidRegion && (!search.trim() || c.name.toLowerCase().includes(search.trim().toLowerCase())) &&
    (region === 'all' || c.region === region) && (!language || c.language === language) && (!sourceType || c.source_type === sourceType) &&
    (tab === 'all' || subscriptionMap.has(c.id)))
  const selectedVisible = visible.filter(c => selected.includes(c.id)).map(c => c.id)
  const allSelected = visible.length > 0 && selectedVisible.length === visible.length

  function run(perform: () => Promise<unknown>, success?: () => void) {
    if (!user) { setLogin(true); return }
    mutation.mutate(perform, { onSuccess: () => { setConfirmation(null); success?.() } })
  }
  function unsubscribe(sourceIds: number[]) {
    const affectedGroups = groups.filter(g => g.source_ids.some(id => sourceIds.includes(id)))
    setConfirmation({ description: `取消订阅 ${sourceIds.length} 个频道${affectedGroups.length ? `，同时从以下分组移除：${affectedGroups.map(g => g.name).join('、')}` : ''}。`,
      perform: () => changeChannelSubscriptions({ action: 'unsubscribe', source_ids: sourceIds }) })
  }

  return <div className="mx-auto max-w-6xl px-4 py-6">
    <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="text-2xl font-bold">频道管理</h1><p className="mt-1 text-sm text-muted-foreground">订阅来源，并将频道整理到一个或多个个人分组。</p></div>
      <Link to={returnTo} className="text-sm text-primary underline">返回资讯</Link>
    </header>
    {config.accounts && !user && !loading && <div className="mb-4 rounded-xl bg-secondary p-4 text-sm">登录后订阅频道，分组与阅读范围会随账号同步。 <Button onClick={() => setLogin(true)} variant="outline">登录</Button></div>}
    {!config.accounts && <p role="status" className="mb-4 text-sm text-muted-foreground">当前仅提供频道目录与全部资讯。</p>}
    {login && <AuthModal onClose={() => setLogin(false)} />}
    <nav aria-label="频道管理视图" className="mb-4 flex gap-2">
      {([{ key: 'all', label: '全部频道' }, ...(config.enabled ? [{ key: 'subscribed', label: '已订阅' }, { key: 'groups', label: '分组管理' }] : [])] as const).map(t =>
        <Button key={t.key} aria-pressed={tab === t.key} variant={tab === t.key ? 'default' : 'outline'} onClick={() => { setTab(t.key as typeof tab); setSelected([]) }}>{t.label}</Button>)}
    </nav>
    {(directory.isError || config.error) && <div role="alert" className="mb-4 text-sm text-red-700">频道配置加载失败。 <button className="underline" onClick={() => { void directory.refetch(); void config.retry() }}>重试</button></div>}
    {invalidRegion && <p role="alert" className="mb-3">无效的频道地区，请选择全部、国内或国际。</p>}
    {mutation.isError && <p role="alert" className="mb-4 text-sm text-red-700">{errorMessage(mutation.error)}</p>}
    {confirmation && <ChannelConfirmationDialog description={confirmation.description} pending={mutation.isPending}
      error={mutation.isError ? errorMessage(mutation.error) : undefined}
      onConfirm={() => run(confirmation.perform)} onCancel={() => setConfirmation(null)} />}
    {loading || directory.isPending || (config.enabled && !config.ready && !config.error) ? <LoadingSpinner /> : directory.isSuccess && !config.error ? <>
      {tab === 'groups' && config.enabled && <section aria-label="个人分组" className="mb-5 rounded-xl border border-border bg-card p-4">
        <form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); run(() => createChannelGroup(newName.trim()), () => setNewName('')) }}>
          <label className="flex items-center gap-2">新分组<input aria-label="新分组名称" disabled={!writable} maxLength={40} required value={newName} onChange={e => setNewName(e.target.value)} className={control} /></label>
          <Button disabled={!writable || !newName.trim()}>创建分组</Button>
        </form>
        <div className="my-4 flex flex-wrap gap-2">{groups.map(g => <Button key={g.id} variant={g.id === currentGroup?.id ? 'default' : 'outline'} aria-pressed={g.id === currentGroup?.id} onClick={() => { setGroupId(g.id); setSelected([]) }}>{g.name} ({g.source_ids.length})</Button>)}</div>
        {currentGroup ? <>
          <GroupNameEditor key={`${currentGroup.id}:${currentGroup.name}`} group={currentGroup} disabled={!writable} onRename={name => run(() => updateChannelGroup(currentGroup.id, { name }))} />
          <Button className="mt-2" variant="outline" disabled={!writable} onClick={() => setConfirmation({ description: `删除“${currentGroup.name}”分组，频道订阅会保留。`, perform: () => deleteChannelGroup(currentGroup.id) })}>删除分组</Button>
          <p className="mt-3 text-sm text-muted-foreground">选择下方已订阅频道，批量添加或移除。移除只影响当前分组。</p>
          {currentGroup.source_ids.length === 0 && <p role="status" className="mt-2 text-sm">空分组：选择下方频道后点击“添加到当前分组”。</p>}
        </> : <p role="status" className="text-sm text-muted-foreground">还没有分组，创建后即可整理已订阅频道。</p>}
      </section>}
      <RegionFilter value={region} onChange={value => { setRegion(value); setSelected([]) }} />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <label className="text-sm">频道名称<input type="search" placeholder="搜索频道" value={search} onChange={e => setSearch(e.target.value)} className={`${control} mt-1 w-full`} /></label>
        <label className="text-sm">语言<select value={language} onChange={e => setLanguage(e.target.value)} className={`${control} mt-1 w-full`}><option value="">全部语言</option>{[...new Set(directory.data.map(c => c.language))].map(l => <option key={l} value={l}>{l === 'en' ? '英文' : l === 'zh' ? '中文' : l}</option>)}</select></label>
        <label className="text-sm">来源类型<select value={sourceType} onChange={e => setSourceType(e.target.value)} className={`${control} mt-1 w-full`}><option value="">全部类型</option><option value="news">新闻媒体</option><option value="aggregator">聚合平台</option><option value="discussion">讨论社区</option></select></label>
      </div>
      {config.enabled && <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl bg-secondary p-3 text-sm">
        <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? [] : visible.map(c => c.id))} />选择当前列表全部频道</label>
        <span>已选 {selectedVisible.length} 个</span>
        {tab === 'groups' && currentGroup ? <>
          <Button disabled={!writable || !selectedVisible.length} onClick={() => run(() => updateChannelGroup(currentGroup.id, { add_source_ids: selectedVisible }))}>添加到当前分组</Button>
          <Button variant="outline" disabled={!writable || !selectedVisible.length} onClick={() => run(() => updateChannelGroup(currentGroup.id, { remove_source_ids: selectedVisible }))}>从当前分组移除</Button>
        </> : <>
          <Button disabled={!writable || !visible.some(c => selected.includes(c.id) && c.subscription_status === 'active' && !subscriptionMap.has(c.id))} onClick={() => run(() => changeChannelSubscriptions({ action: 'subscribe', source_ids: visible.filter(c => selected.includes(c.id) && c.subscription_status === 'active').map(c => c.id) }))}>批量订阅</Button>
          <Button variant="outline" disabled={!writable || !selectedVisible.some(id => subscriptionMap.has(id))} onClick={() => unsubscribe(selectedVisible.filter(id => subscriptionMap.has(id)))}>批量取消订阅</Button>
        </>}
      </div>}
      {visible.length === 0 && <div role="status" className="py-10 text-center text-muted-foreground">
        <p>{tab !== 'all' && subscriptionMap.size === 0 ? '还没有订阅频道。' : '没有匹配的频道。'}</p>
        <Button className="mt-3" variant="outline" onClick={() => { setTab('all'); setSearch(''); setRegion('all'); setLanguage(''); setSourceType('') }}>选择频道</Button>
      </div>}
      <div className="grid gap-4 md:grid-cols-2">{visible.map(channel => {
        const subscription = subscriptionMap.get(channel.id)
        const memberNames = groups.filter(g => subscription?.group_ids.includes(g.id)).map(g => g.name)
        return <article key={channel.id} className="min-w-0 rounded-xl border border-border bg-card p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0"><h2 className="break-words font-semibold">{channel.name}</h2><p className="mt-1 text-xs text-muted-foreground">{channel.region === 'domestic' ? '国内' : '国际'} · {channel.language} · {channel.source_type === 'news' ? '新闻媒体' : channel.source_type === 'aggregator' ? '聚合平台' : '讨论社区'} · {channel.news_count} 篇资讯</p></div>
            {config.enabled && <label className="flex min-h-11 shrink-0 items-center gap-2 text-sm"><input aria-label={`选择 ${channel.name}`} type="checkbox" checked={selected.includes(channel.id)} onChange={e => setSelected(previous => e.target.checked ? [...previous, channel.id] : previous.filter(id => id !== channel.id))} />选择</label>}
          </div>
          {channel.reading_policy === 'rss_summary_only' && <p className="mt-2 text-xs text-muted-foreground">仅提供 RSS 标题、摘要和原文链接</p>}
          <p className="mt-3 text-sm text-muted-foreground">{channel.description || `来自 ${channel.name} 的资讯`}</p>
          <p className="mt-2 text-sm">{subscription ? `已订阅 · ${memberNames.length ? memberNames.join('、') : '未加入分组'}` : '未订阅'}{channel.subscription_status === 'inactive' ? (channel.subscription_reason === 'feed_verification_pending' ? ' · RSS 待验证，暂未启用' : ' · 已停用，保留历史阅读') : ''}</p>
          {config.accounts && <Button className="mt-3" variant={subscription ? 'outline' : 'default'} disabled={mutation.isPending || (config.enabled && !writable) || (!subscription && channel.subscription_status !== 'active')}
            onClick={() => { if (!user) setLogin(true); else if (subscription) unsubscribe([channel.id]); else run(() => changeChannelSubscriptions({ action: 'subscribe', source_ids: [channel.id] })) }}>{subscription ? '取消订阅' : '订阅'}</Button>}
          {subscription && groups.length > 0 && <fieldset className="mt-3 border-t border-border pt-3"><legend className="text-xs text-muted-foreground">所属分组（可多选）</legend><div className="flex flex-wrap gap-x-4">{groups.map(g => <label key={g.id} className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" disabled={!writable} checked={subscription.group_ids.includes(g.id)} onChange={e => {
            const groupIds = e.target.checked ? [...subscription.group_ids, g.id] : subscription.group_ids.filter(id => id !== g.id)
            run(() => changeChannelSubscriptions({ action: 'set_groups', source_ids: [channel.id], group_ids: groupIds }))
          }} />{g.name}</label>)}</div></fieldset>}
          {tab === 'groups' && currentGroup && <p className="mt-2 text-xs text-muted-foreground">{currentGroup.source_ids.includes(channel.id) ? `已加入 ${currentGroup.name}` : `未加入 ${currentGroup.name}`}</p>}
        </article>
      })}</div>
    </> : null}
  </div>
}

function GroupNameEditor({ group, disabled, onRename }: { group: ChannelGroup; disabled: boolean; onRename: (name: string) => void }) {
  const [name, setName] = useState(group.name)
  return <form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); onRename(name.trim()) }}>
    <label className="flex items-center gap-2">分组名称<input aria-label="分组名称" disabled={disabled} className={control} required maxLength={40} value={name} onChange={e => setName(e.target.value)} /></label>
    <Button variant="outline" disabled={disabled || !name.trim() || name.trim() === group.name}>重命名</Button>
  </form>
}
