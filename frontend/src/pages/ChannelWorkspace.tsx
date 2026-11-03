import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { LayoutGrid, List, Plus, Search, SlidersHorizontal, Sparkles } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { Button } from '@/components/ui/button'
import AuthModal from '@/components/AuthModal'
import { changeChannelSubscriptions, updateChannelGroup } from '@/services/api'
import { useChannelConfig, useChannelMutation } from '@/services/channelQueries'
import { workspaceCatalogOptions, workspaceKeys, type ChannelProfile } from '@/services/workspaceApi'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import AddChannelDialog from '@/components/workspace/AddChannelDialog'
import OpmlDialog from '@/features/rss/OpmlDialog'
import ConnectionStatus from '@/features/rss/ConnectionStatus'
import RecommendChannelsDialog from '@/features/rss/RecommendChannelsDialog'
import { canRecommendChannel } from '@/features/rss/recommendationEligibility'
import { Availability, ChannelMark, TopicTags } from '@/components/workspace/ChannelIdentity'
import { channelGroupPath } from '@/types/channels'

export default function ChannelWorkspace() {
  const { user } = useAuth()
  return <Directory key={user?.id ?? 'anonymous'} />
}

function Directory() {
  const { user } = useAuth()
  const config = useChannelConfig()
  const mutation = useChannelMutation()
  const client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'all'
  const catalog = useQuery(workspaceCatalogOptions(config.viewer, tab === 'subscribed' ? 'history' : 'subscribe'))
  const [view, setView] = useState<'table' | 'grid'>('table')
  const [filters, setFilters] = useState(false)
  const [selected, setSelected] = useState<number[]>([])
  const [login, setLogin] = useState(false)
  const [adding, setAdding] = useState(false)
  const [importing, setImporting] = useState(false)
  const [editing, setEditing] = useState<number | null>(null)
  const [cancelIds, setCancelIds] = useState<number[] | null>(null)
  const [bulkGroup, setBulkGroup] = useState('')
  const [notice, setNotice] = useState('')
  const [recommending, setRecommending] = useState<ChannelProfile[] | null>(null)
  const sources = catalog.data?.sources ?? []
  const topics = catalog.data?.topics ?? []
  const subscriptions = new Map((config.subscriptions.data ?? []).map(subscription => [subscription.source_id, subscription]))
  const groups = config.groups.data ?? []
  const roots = config.roots.data ?? []
  const region = params.get('region') ?? ''
  const language = params.get('language') ?? ''
  const sourceType = params.get('type') ?? ''
  const topic = params.get('topic') ?? ''
  const search = params.get('q') ?? ''
  const invalid = !['all', 'subscribed', 'unsubscribed', 'pending'].includes(tab) || !['', 'domestic', 'international'].includes(region)
  const filtered = sources.filter(source => !invalid && (!region || source.region === region) && (!language || source.language === language)
    && (!sourceType || source.source_type === sourceType) && (!topic || source.topics.includes(topic))
    && (!search.trim() || (source.name + ' ' + source.description).toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
    && (tab === 'pending' ? source.subscription_status !== 'active' : tab === 'subscribed' || source.subscription_status === 'active')
    && (tab === 'all' || tab === 'pending' || (config.ready && !config.error && (tab === 'subscribed' ? subscriptions.has(source.id) : !subscriptions.has(source.id)))))
  const selectedVisible = filtered.filter(source => selected.includes(source.id))
  const recommendable = selectedVisible.filter(source => subscriptions.has(source.id) && canRecommendChannel(source))
  const writable = config.enabled && config.ready && !config.error && !mutation.isPending
  const editedSource = sources.find(source => source.id === editing)
  const editedSubscription = editing === null ? undefined : subscriptions.get(editing)
  const affectedGroups = groups.filter(group => cancelIds?.some(id => group.source_ids.includes(id)))
  const change = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value); else next.delete(key)
    setParams(next, { replace: key === 'q' })
    setSelected([])
  }
  const run = (perform: () => Promise<unknown>, message: string, after?: () => void) => {
    if (!user) { setLogin(true); return }
    mutation.mutate(perform, { onSuccess: () => { setNotice(message); void client.invalidateQueries({ queryKey: workspaceKeys.all }); after?.() } })
  }
  function subscribe(source: ChannelProfile) {
    run(() => changeChannelSubscriptions({ action: 'subscribe', source_ids: [source.id] }), '已订阅 ' + source.name)
  }
  const allSelected = filtered.length > 0 && selectedVisible.length === filtered.length
  return <div className="workspace-page">
    {user?.isSuperuser && <Link className="workspace-link" to="/admin/rss/channels">处理待核验频道</Link>}
    <header className="workspace-page-heading"><div><p className="workspace-eyebrow">你的信息来源</p><h1>频道管理</h1><p>发现并订阅优质来源，用主题与分组构建自己的资讯流。</p></div>
      <div className="workspace-actions">{user && <Link className="workspace-button secondary" to="/channels/additions">添加记录</Link>}{config.enabled && <Button type="button" variant="outline" disabled={!config.ready || !!config.error} onClick={() => setImporting(true)}>OPML 批量导入</Button>}{config.accounts && <Link className="workspace-button secondary" to="/channels/smart"><Sparkles size={16} aria-hidden="true" />智能整理</Link>}
        {config.accounts && <button type="button" className="workspace-button" onClick={() => user ? setAdding(true) : setLogin(true)}><Plus size={16} aria-hidden="true" />添加频道</button>}</div>
    </header>
    {config.enabled && user && <ConnectionStatus viewer={user.id} admin={user.isSuperuser} />}
    {config.enabled && user && <p className="workspace-soft-panel">把你发现的优质公开 RSS 推荐给大家，审核通过后会加入公共频道。<Link to="/channels/additions?tab=recommendations">查看我的推荐与审核状态</Link></p>}
    <div className="workspace-tabs" role="group" aria-label="频道范围">{[
      { key: 'all', label: '全部频道', count: sources.filter(source => source.subscription_status === 'active').length },
      { key: 'pending', label: '待验证候选', count: sources.filter(source => source.subscription_status !== 'active').length },
      ...(config.enabled ? [{ key: 'subscribed', label: '已订阅', count: subscriptions.size }, { key: 'unsubscribed', label: '未订阅', count: sources.filter(source => source.subscription_status === 'active' && !subscriptions.has(source.id)).length }] : []),
    ].map(item => <button key={item.key} type="button" aria-pressed={tab === item.key} onClick={() => change('tab', item.key)}>{item.label}<small>{item.count}</small></button>)}</div>
    <section className="workspace-filter-toolbar" aria-label="查找频道">
      <label className="workspace-search"><Search size={16} aria-hidden="true" /><input type="search" aria-label="搜索频道" placeholder="搜索频道名称、简介…" value={search} onChange={event => change('q', event.target.value)} /></label>
      <label className="workspace-sr-label">频道地区<select value={region} onChange={event => change('region', event.target.value)}><option value="">全部地区</option><option value="domestic">国内</option><option value="international">国际</option></select></label>
      <label className="workspace-sr-label">主题<select value={topic} onChange={event => change('topic', event.target.value)}><option value="">全部主题</option>{topics.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label>
      <button type="button" className="workspace-button secondary" aria-expanded={filters} onClick={() => setFilters(value => !value)}><SlidersHorizontal size={15} aria-hidden="true" />更多筛选</button>
      <div className="workspace-view-switch" role="group" aria-label="频道展示方式"><button type="button" aria-label="列表视图" aria-pressed={view === 'table'} onClick={() => setView('table')}><List size={17} aria-hidden="true" /></button><button type="button" aria-label="卡片视图" aria-pressed={view === 'grid'} onClick={() => setView('grid')}><LayoutGrid size={17} aria-hidden="true" /></button></div>
      {(filters || language || sourceType) && <div className="workspace-filter-extra"><label>语言<select value={language} onChange={event => change('language', event.target.value)}><option value="">全部语言</option><option value="zh">中文</option><option value="en">英文</option></select></label>
        <label>来源类型<select value={sourceType} onChange={event => change('type', event.target.value)}><option value="">全部类型</option><option value="news">新闻媒体</option><option value="aggregator">聚合平台</option><option value="discussion">讨论社区</option></select></label>
        <button type="button" className="workspace-link" onClick={() => { setParams({ tab }); setSelected([]) }}>清除频道筛选</button></div>}
    </section>
    {invalid && <p role="alert" className="workspace-error">无效的频道筛选。<button type="button" onClick={() => setParams({})}>恢复全部频道</button></p>}
    {config.error && <p role="alert" className="workspace-error">个人订阅加载失败，暂不可修改。<button type="button" onClick={() => void config.retry()}>重试</button></p>}
    {catalog.isError && <p role="alert" className="workspace-error">频道目录加载失败。<button type="button" onClick={() => void catalog.refetch()}>重试</button></p>}
    {mutation.isError && <p role="alert" className="workspace-error">保存失败，请重试；原有订阅和分组不会被清空。</p>}
    {notice && <p role="status" className="workspace-notice">{notice}<button type="button" onClick={() => setNotice('')} aria-label="关闭操作提示">×</button></p>}
    {selectedVisible.length > 0 && config.enabled && <div className="workspace-bulk-bar" role="region" aria-label="批量操作"><strong>已选择 {selectedVisible.length} 个频道</strong>
      <Button variant="outline" disabled={!writable || !recommendable.length || recommendable.length > 10} onClick={() => setRecommending(recommendable)}>推荐所选个人频道（{recommendable.length}/10）</Button>
      {recommendable.length > 10 && <span role="status">每次最多推荐 10 个，请减少选择。</span>}
      <button type="button" className="workspace-button secondary" disabled={!writable || !selectedVisible.some(source => source.subscription_status === 'active' && !subscriptions.has(source.id))}
        onClick={() => run(() => changeChannelSubscriptions({ action: 'subscribe', source_ids: selectedVisible.filter(source => source.subscription_status === 'active' && !subscriptions.has(source.id)).map(source => source.id) }), '批量订阅完成')}>批量订阅</button>
      <button type="button" className="workspace-button secondary" disabled={!writable || !selectedVisible.some(source => subscriptions.has(source.id))} onClick={() => setCancelIds(selectedVisible.filter(source => subscriptions.has(source.id)).map(source => source.id))}>取消订阅</button>
      <select aria-label="批量加入分组" value={bulkGroup} onChange={event => setBulkGroup(event.target.value)}><option value="">选择目标分组</option>{groups.map(group => <option key={group.id} value={group.id}>{channelGroupPath(group, roots)}</option>)}</select>
      <button type="button" className="workspace-button secondary" disabled={!writable || !bulkGroup || !selectedVisible.some(source => subscriptions.has(source.id))} onClick={() => run(() => updateChannelGroup(Number(bulkGroup), { add_source_ids: selectedVisible.filter(source => subscriptions.has(source.id)).map(source => source.id) }), '已添加到分组')}>加入分组</button>
      <button type="button" className="workspace-link" onClick={() => setSelected([])}>清空选择</button>
    </div>}
    <div className={'workspace-channel-list ' + (view === 'grid' ? 'is-grid' : '')}>
      <div className="workspace-table-heading">{config.enabled && <label><input type="checkbox" aria-label="全选当前结果" checked={allSelected} onChange={() => setSelected(allSelected ? [] : filtered.map(source => source.id))} />频道</label>}<span>主题标签</span><span>地区 / 语言</span><span>订阅与操作</span></div>
      {catalog.isPending && <p role="status" className="workspace-empty">正在加载频道…</p>}
      {filtered.map(source => {
        const subscribed = subscriptions.has(source.id)
        return <article className="workspace-channel-row" key={source.id}>
          <div className="workspace-channel-identity">{config.enabled && <input type="checkbox" aria-label={'选择 ' + source.name} checked={selected.includes(source.id)} onChange={event => setSelected(current => event.target.checked ? [...current, source.id] : current.filter(id => id !== source.id))} />}
            <ChannelMark source={source} /><div><Link className="workspace-source-title" to={'/channels/' + source.id}>{source.name}</Link><p>{source.description || '暂无频道简介，可在详情中查看收录内容。'}</p><small>{source.news_count} 篇资讯</small></div></div>
          <TopicTags keys={source.topics} topics={topics} />
          <span className="workspace-channel-locale">{source.region === 'domestic' ? '国内' : '国际'} · {source.language === 'zh' ? '中文' : source.language === 'en' ? '英文' : source.language}</span>
          <div className="workspace-channel-actions">{config.accounts && <button type="button" className={'workspace-button ' + (subscribed ? 'subscribed' : 'secondary')} disabled={mutation.isPending || (!!user && !writable) || (!subscribed && source.subscription_status !== 'active')}
            onClick={() => subscribed ? setEditing(source.id) : subscribe(source)}>{subscribed ? '✓ 已订阅' : '+ 订阅'}</button>}
            {subscribed && config.enabled && canRecommendChannel(source) && <Button variant="outline" disabled={!writable} onClick={() => setRecommending([source])}>推荐到公共频道</Button>}
            <Link className="workspace-link" to={'/channels/' + source.id}>详情</Link><Availability source={source} /></div>
        </article>
      })}
      {!catalog.isPending && !catalog.isError && !filtered.length && <div className="workspace-empty"><h2>没有匹配的频道</h2><p>调整筛选条件，或从全部频道中选择新的来源。</p><button type="button" className="workspace-button secondary" onClick={() => setParams({})}>查看全部频道</button></div>}
    </div>
    {login && <AuthModal onClose={() => setLogin(false)} />}
    {recommending && user && <RecommendChannelsDialog viewer={user.id} sources={recommending} onClose={() => setRecommending(null)} />}
    {importing && user && <OpmlDialog viewer={user.id} roots={roots} groups={groups} onClose={() => setImporting(false)} />}
    {adding && <AddChannelDialog topics={topics} onClose={() => setAdding(false)} onDone={() => { setAdding(false); setNotice('订阅已保存，可在频道列表查看连接状态。') }} />}
    {editedSource && editedSubscription && <WorkspaceModal title={editedSource.name + ' · 订阅设置'} busy={mutation.isPending} onClose={() => setEditing(null)}>
      <p className="workspace-muted">一个频道可以加入多个分组，手动移出后不会被自动加回。</p>
      <fieldset className="workspace-group-checkboxes"><legend>所属子分组（最多 3 个）</legend>{groups.map(group => <label key={group.id}><input type="checkbox" disabled={!writable || (!editedSubscription.group_ids.includes(group.id) && editedSubscription.group_ids.length >= 3)} checked={editedSubscription.group_ids.includes(group.id)} onChange={event => {
        const groupIds = event.target.checked ? [...editedSubscription.group_ids, group.id] : editedSubscription.group_ids.filter(id => id !== group.id)
        run(() => changeChannelSubscriptions({ action: 'set_groups', source_ids: [editedSource.id], group_ids: groupIds }), '分组已更新')
      }} />{channelGroupPath(group, roots)}</label>)}</fieldset>
      {!groups.length && <Link className="workspace-link" to="/channels/groups">先创建一个分组 →</Link>}
      <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={mutation.isPending} onClick={() => { setEditing(null); setCancelIds([editedSource.id]) }}>取消订阅</button><button type="button" className="workspace-button" disabled={mutation.isPending} onClick={() => setEditing(null)}>完成</button></footer>
    </WorkspaceModal>}
    {cancelIds && <WorkspaceModal title="确认取消订阅" busy={mutation.isPending} onClose={() => setCancelIds(null)}><p>取消 {cancelIds.length} 个频道的订阅，同时移除它们的分组归属。</p>{affectedGroups.length > 0 && <p className="workspace-muted">受影响分组：{affectedGroups.map(group => channelGroupPath(group, roots)).join('、')}</p>}
      {mutation.isError && <p role="alert" className="workspace-error">取消订阅失败，请重试。</p>}
      <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={mutation.isPending} onClick={() => setCancelIds(null)}>保留订阅</button><button type="button" className="workspace-button danger" disabled={!writable} onClick={() => run(() => changeChannelSubscriptions({ action: 'unsubscribe', source_ids: cancelIds }), '已取消订阅', () => { setCancelIds(null); setSelected([]) })}>确认取消</button></footer>
    </WorkspaceModal>}
  </div>
}
