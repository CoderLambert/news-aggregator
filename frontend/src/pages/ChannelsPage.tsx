import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { channelDirectoryOptions, useChannelConfig, useChannelMutation } from '@/services/channelQueries'
import { changeChannelSubscriptions, createChannelGroup, updateChannelGroup, deleteChannelGroup } from '@/services/api'
import { isRecord } from '@/types/news'
import type { ChannelGroup } from '@/types/channels'
import { Button } from '@/components/ui/button'
import { ChevronDown, Filter } from 'lucide-react'
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
  const mutation = useChannelMutation()
  const [tab, setTab] = useState<'all' | 'subscribed' | 'groups'>('all')
  const directory = useQuery(channelDirectoryOptions(config.viewer, tab === 'all' ? 'subscribe' : 'history'))
  const [search, setSearch] = useState('')
  const [moreFilters, setMoreFilters] = useState(false)
  const [editingMembership, setEditingMembership] = useState<number | null>(null)
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

  function run(perform: () => Promise<unknown>, success?: (result: unknown) => void) {
    if (!user) { setLogin(true); return }
    mutation.mutate(perform, { onSuccess: result => { setConfirmation(null); success?.(result) } })
  }
  function unsubscribe(sourceIds: number[]) {
    const affectedGroups = groups.filter(g => g.source_ids.some(id => sourceIds.includes(id)))
    setConfirmation({ description: `取消订阅 ${sourceIds.length} 个频道${affectedGroups.length ? `，同时从以下分组移除：${affectedGroups.map(g => g.name).join('、')}` : ''}。`,
      perform: () => changeChannelSubscriptions({ action: 'unsubscribe', source_ids: sourceIds }) })
  }

  return <div className="mx-auto max-w-6xl px-4 py-6">
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="mb-1 text-xs font-semibold tracking-widest text-primary">PERSONAL SOURCES</p>
        <h1 className="text-2xl font-bold tracking-tight">频道管理</h1>
        <p className="mt-1 text-sm text-muted-foreground">发现值得关注的来源，把感兴趣的频道收进自己的资讯流。</p>
      </div>
      <div className="flex items-center gap-4 text-sm">
        {config.enabled && config.ready && <span className="rounded-full bg-secondary px-3 py-2 text-muted-foreground"><strong className="text-foreground">{subscriptionMap.size}</strong> 个已订阅</span>}
        <Link to={returnTo} className="inline-flex min-h-11 items-center text-primary hover:underline">返回资讯 <span aria-hidden="true" className="ml-1">→</span></Link>
      </div>
    </header>
    {config.accounts && !user && !loading && <div className="mb-4 rounded-xl bg-secondary p-4 text-sm">登录后订阅频道，分组与阅读范围会随账号同步。 <Button onClick={() => setLogin(true)} variant="outline">登录</Button></div>}
    {!config.accounts && <p role="status" className="mb-4 text-sm text-muted-foreground">当前仅提供频道目录与全部资讯。</p>}
    {login && <AuthModal onClose={() => setLogin(false)} />}
    <div className="grid gap-5 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-6">
      <aside className="h-fit rounded-2xl border border-border bg-card p-3 lg:sticky lg:top-20">
        <p className="mb-2 hidden px-3 pt-2 text-xs font-semibold tracking-wide text-muted-foreground lg:block">频道导航</p>
        <nav aria-label="频道管理视图" className="flex flex-wrap gap-1.5 lg:flex-col">
          {([{ key: 'all', label: '全部频道', count: directory.data?.length ?? 0 },
            ...(config.enabled ? [{ key: 'subscribed', label: '已订阅', count: subscriptionMap.size },
              { key: 'groups', label: '分组管理', count: groups.length }] : [])] as const).map(t =>
            <Button key={t.key} aria-pressed={tab === t.key} variant={tab === t.key ? 'default' : 'ghost'}
              className="justify-between rounded-xl px-3 text-sm lg:w-full"
              onClick={() => { setTab(t.key as typeof tab); setSelected([]); setEditingMembership(null) }}>
              <span>{t.label}</span><span aria-hidden="true" className="ml-3 text-xs opacity-70">{t.count}</span>
            </Button>)}
        </nav>
        <p className="mt-4 hidden border-t border-border px-3 pt-4 text-xs leading-6 text-muted-foreground lg:block">
          {tab === 'groups' ? '一个频道可以归入多个分组。移出分组不会取消订阅。'
            : '订阅决定你关注哪些来源，分组帮助你在首页快速切换阅读范围。'}
        </p>
      </aside>
      <main className="min-w-0">
    {(directory.isError || config.error) && <div role="alert" className="mb-4 text-sm text-red-700">频道配置加载失败。 <button className="underline" onClick={() => { void directory.refetch(); void config.retry() }}>重试</button></div>}
    {invalidRegion && <p role="alert" className="mb-3">无效的频道地区，请选择全部、国内或国际。</p>}
    {mutation.isError && <p role="alert" className="mb-4 text-sm text-red-700">{errorMessage(mutation.error)}</p>}
    {confirmation && <ChannelConfirmationDialog description={confirmation.description} pending={mutation.isPending}
      error={mutation.isError ? errorMessage(mutation.error) : undefined}
      onConfirm={() => run(confirmation.perform)} onCancel={() => setConfirmation(null)} />}
    {loading || directory.isPending || (config.enabled && !config.ready && !config.error) ? <LoadingSpinner /> : directory.isSuccess && !config.error ? <>
      {tab === 'groups' && config.enabled && <section aria-label="个人分组" className="mb-4 rounded-2xl border border-border bg-card p-4 sm:p-5">
        <div className="mb-4">
          <h2 className="font-semibold">我的分组</h2>
          <p className="mt-1 text-xs text-muted-foreground">通过分组整理已订阅频道，不影响原有订阅关系。</p>
        </div>
        <form className="flex flex-wrap items-end gap-2" onSubmit={e => { e.preventDefault(); run(() => createChannelGroup(newName.trim()), result => { setNewName(''); if (isRecord(result) && typeof result.id === 'number') setGroupId(result.id) }) }}>
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs text-muted-foreground">新分组名称
            <input aria-label="新分组名称" placeholder="例如：人工智能" disabled={!writable} maxLength={40} required value={newName} onChange={e => setNewName(e.target.value)} className={control} />
          </label>
          <Button disabled={!writable || !newName.trim()}>创建分组</Button>
        </form>
        <div className="my-4 flex flex-wrap gap-2">{groups.map(g => <Button key={g.id} variant={g.id === currentGroup?.id ? 'default' : 'outline'} aria-pressed={g.id === currentGroup?.id}
          onClick={() => { setGroupId(g.id); setSelected([]) }}>{g.name} ({g.source_ids.length})</Button>)}</div>
        {currentGroup ? <div className="rounded-xl bg-secondary/50 p-3">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <GroupNameEditor key={currentGroup.id + ':' + currentGroup.name} group={currentGroup} disabled={!writable} onRename={name => run(() => updateChannelGroup(currentGroup.id, { name }))} />
            <Button variant="outline" disabled={!writable} onClick={() => setConfirmation({ description: '删除“' + currentGroup.name + '”分组，频道订阅会保留。', perform: () => deleteChannelGroup(currentGroup.id) })}>删除分组</Button>
          </div>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">在下方选择已订阅频道，可批量添加或移除当前分组中的成员。</p>
          {currentGroup.source_ids.length === 0 && <p role="status" className="mt-2 text-sm">空分组：选择下方频道后点击“添加到当前分组”。</p>}
        </div> : <p role="status" className="text-sm text-muted-foreground">还没有分组，创建后即可整理已订阅频道。</p>}
      </section>}
      <section aria-label="查找频道" className="mb-4 rounded-2xl border border-border bg-card p-3 sm:p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[12rem] flex-1 text-xs text-muted-foreground">频道名称
            <input type="search" placeholder="搜索频道名称..." value={search} onChange={e => setSearch(e.target.value)} className={control + ' mt-1 w-full'} />
          </label>
          <RegionFilter compact value={region} onChange={value => { setRegion(value); setSelected([]) }} />
          <button type="button" aria-expanded={moreFilters} onClick={() => setMoreFilters(value => !value)}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm text-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-primary">
            <Filter aria-hidden="true" className="size-4" />更多筛选{language || sourceType ? ' · 已启用' : ''}<ChevronDown aria-hidden="true" className="size-4" />
          </button>
        </div>
        {(moreFilters || language || sourceType) && <div className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-2">
          <label className="text-xs text-muted-foreground">语言
            <select value={language} onChange={e => setLanguage(e.target.value)} className={control + ' mt-1 w-full'}>
              <option value="">全部语言</option>{[...new Set(directory.data.map(c => c.language))].map(l => <option key={l} value={l}>{l === 'en' ? '英文' : l === 'zh' ? '中文' : l}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted-foreground">来源类型
            <select value={sourceType} onChange={e => setSourceType(e.target.value)} className={control + ' mt-1 w-full'}>
              <option value="">全部类型</option><option value="news">新闻媒体</option><option value="aggregator">聚合平台</option><option value="discussion">讨论社区</option>
            </select>
          </label>
        </div>}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border/70 pt-3 text-xs text-muted-foreground">
          <span>找到 <strong className="text-foreground">{visible.length}</strong> 个频道</span>
          {config.enabled && visible.length > 0 && <button type="button" className="min-h-9 rounded-lg px-2 text-primary hover:bg-secondary"
            onClick={() => setSelected(allSelected ? [] : visible.map(c => c.id))}>{allSelected ? '取消全选' : '全选当前结果'}</button>}
        </div>
      </section>
      {config.enabled && selectedVisible.length > 0 && <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm">
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
      <div className="grid gap-3">{visible.map(channel => {
        const subscription = subscriptionMap.get(channel.id)
        const memberNames = groups.filter(g => subscription?.group_ids.includes(g.id)).map(g => g.name)
        const membershipOpen = editingMembership === channel.id
        return <article key={channel.id} className="min-w-0 rounded-2xl border border-border bg-card p-4 transition-colors hover:border-primary/30">
          <div className="flex flex-wrap items-start justify-between gap-3 sm:flex-nowrap">
            <div className="min-w-0 flex-1">
              <h2 className="break-words text-base font-semibold">{channel.name}</h2>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                <span>{channel.region === 'domestic' ? '国内' : '国际'} · {channel.language === 'zh' ? '中文' : channel.language === 'en' ? '英文' : channel.language}</span>
                <span aria-hidden="true">·</span>
                <span>{channel.source_type === 'news' ? '新闻媒体' : channel.source_type === 'aggregator' ? '聚合平台' : '讨论社区'}</span>
                <span aria-hidden="true">·</span><span>{channel.news_count} 篇资讯</span>
              </div>
              <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{channel.description || '来自 ' + channel.name + ' 的资讯'}</p>
              {channel.reading_policy === 'rss_summary_only' && <p className="mt-1 text-xs text-muted-foreground">仅提供 RSS 摘要与原文链接</p>}
            </div>
            <div className="flex shrink-0 items-center gap-3">
              {config.enabled && <label className="flex min-h-11 items-center gap-2 text-sm text-muted-foreground">
                <input aria-label={'选择 ' + channel.name} type="checkbox" checked={selected.includes(channel.id)}
                  onChange={e => setSelected(previous => e.target.checked ? [...previous, channel.id] : previous.filter(id => id !== channel.id))} />
                <span className="sr-only">选择</span>
              </label>}
              {config.accounts && <Button variant={subscription ? 'outline' : 'default'} disabled={mutation.isPending || (config.enabled && !writable) || (!subscription && channel.subscription_status !== 'active')}
                onClick={() => { if (!user) setLogin(true); else if (subscription) unsubscribe([channel.id]); else run(() => changeChannelSubscriptions({ action: 'subscribe', source_ids: [channel.id] })) }}>
                {subscription ? '取消订阅' : '订阅'}
              </Button>}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border/70 pt-2">
            <p className={subscription ? 'text-xs font-medium text-primary' : 'text-xs text-muted-foreground'}>
              {subscription ? '已订阅 · ' + (memberNames.length ? memberNames.join('、') : '未加入分组') : '未订阅'}
              {channel.subscription_status === 'inactive' ? (channel.subscription_reason === 'feed_verification_pending' ? ' · RSS 待验证，暂未启用' : ' · 已停用，保留历史阅读') : ''}
            </p>
            {subscription && groups.length > 0 && <button type="button" aria-expanded={membershipOpen}
              onClick={() => setEditingMembership(current => current === channel.id ? null : channel.id)}
              className="inline-flex min-h-9 items-center gap-1 rounded-lg px-2 text-xs font-medium text-primary hover:bg-secondary focus-visible:outline-2 focus-visible:outline-primary">
              管理分组 <ChevronDown aria-hidden="true" className="size-3" />
            </button>}
          </div>
          {subscription && membershipOpen && groups.length > 0 && <fieldset className="mt-2 rounded-xl bg-secondary/60 p-3">
            <legend className="px-1 text-xs text-muted-foreground">所属分组（可多选）</legend>
            <div className="flex flex-wrap gap-x-4">{groups.map(g => <label key={g.id} className="flex min-h-11 items-center gap-2 text-sm">
              <input type="checkbox" disabled={!writable} checked={subscription.group_ids.includes(g.id)}
                onChange={e => {
                  const groupIds = e.target.checked ? [...subscription.group_ids, g.id] : subscription.group_ids.filter(id => id !== g.id)
                  run(() => changeChannelSubscriptions({ action: 'set_groups', source_ids: [channel.id], group_ids: groupIds }))
                }} />{g.name}
            </label>)}</div>
          </fieldset>}
          {tab === 'groups' && currentGroup && <p className="mt-2 text-xs text-muted-foreground">
            {currentGroup.source_ids.includes(channel.id) ? '已加入 ' + currentGroup.name : '未加入 ' + currentGroup.name}
          </p>}
        </article>
      })}</div>
    </> : null}
      </main>
    </div>
  </div>
}

function GroupNameEditor({ group, disabled, onRename }: { group: ChannelGroup; disabled: boolean; onRename: (name: string) => void }) {
  const [name, setName] = useState(group.name)
  return <form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); onRename(name.trim()) }}>
    <label className="flex items-center gap-2">分组名称<input aria-label="分组名称" disabled={disabled} className={control} required maxLength={40} value={name} onChange={e => setName(e.target.value)} /></label>
    <Button variant="outline" disabled={disabled || !name.trim() || name.trim() === group.name}>重命名</Button>
  </form>
}
