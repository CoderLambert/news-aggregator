import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FolderOpen, Pencil, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import AuthModal from '@/components/AuthModal'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { ChannelMark, TopicTags } from '@/components/workspace/ChannelIdentity'
import { createChannelGroup, deleteChannelGroup, updateChannelGroup } from '@/services/api'
import { useChannelConfig, useChannelMutation } from '@/services/channelQueries'
import { workspaceCatalogOptions, workspaceRequest } from '@/services/workspaceApi'
import { clearBulkUncertain, isBulkUncertain, markBulkUncertain } from '@/services/bulkWriteBarrier'
import { isRecord } from '@/types/news'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { ModelCombobox } from '@/components/ui/model-combobox'

export default function GroupWorkspace() {
  const { user } = useAuth()
  return <Groups key={user?.id ?? 'anonymous'} />
}

function Groups() {
  const { user, loading } = useAuth()
  const config = useChannelConfig()
  const catalog = useQuery(workspaceCatalogOptions(user?.id ?? 'anonymous', 'history'))
  const mutation = useChannelMutation()
  // Query pending state is notified asynchronously. Fence the request in the
  // same event that submits it, so fast Escape/cancel/re-submit cannot race it.
  const submitting = useRef(false)
  const [params, setParams] = useSearchParams()
  const [login, setLogin] = useState(false)
  const [editor, setEditor] = useState<{ id: number | null; name: string } | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [targetId, setTargetId] = useState('')
  const lifetime = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller
    return () => { controller.abort(); lifetime.current = null }
  }, [])
  const [selected, setSelected] = useState<number[]>([])
  const [notice, setNotice] = useState('')
  const restoredBarrier = !!user && isBulkUncertain(user.id)
  const bulkBlocked = useRef(restoredBarrier)
  const reconciling = useRef(false)
  const [uncertainBulk, setUncertainBulk] = useState(restoredBarrier)
  const [reloadPending, setReloadPending] = useState(false)
  const [reloadFailed, setReloadFailed] = useState(false)
  const groups = config.groups.data ?? []
  const group = groups.find(item => String(item.id) === params.get('group')) ?? groups[0]
  const subscriptions = new Set((config.subscriptions.data ?? []).map(item => item.source_id))
  const sources = (catalog.isError ? [] : catalog.data?.sources ?? []).filter(source => subscriptions.has(source.id)
    && (sourceFilter === 'all' || (sourceFilter === 'current' ? group?.source_ids.includes(source.id) : !(config.subscriptions.data ?? []).find(item => item.source_id === source.id)?.group_ids.length))
    && (!search.trim() || source.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())))
  const chosen = sources.filter(source => selected.includes(source.id)).map(source => source.id)
  const writable = config.enabled && config.ready && !config.error && !mutation.isPending && !uncertainBulk && !reloadPending
  const run = (perform: () => Promise<unknown>, message: string, after?: (value: unknown) => void, reconcileOnError = false) => {
    if (submitting.current || bulkBlocked.current || !lifetime.current || lifetime.current.signal.aborted) return
    submitting.current = true
    mutation.mutate(perform, {
      onSuccess: value => { if (!lifetime.current || lifetime.current.signal.aborted) return; setNotice(message); after?.(value) },
      onError: () => {
        if (reconcileOnError && lifetime.current && !lifetime.current.signal.aborted) {
          bulkBlocked.current = true
          if (user) markBulkUncertain(user.id)
          setUncertainBulk(true)
        }
      },
      onSettled: () => { submitting.current = false },
    })
  }
  const targetGroup = groups.find(item => String(item.id) === targetId) ?? group
  const bulk = (action: 'add_to_group' | 'move_to_group' | 'remove_from_group') => {
    if (!user || !targetGroup || !writable || catalog.isError) return
    const destination = action === 'remove_from_group' ? group : targetGroup
    if (!destination) return
    run(() => workspaceRequest('/me/channel-subscriptions/', { method: 'POST', viewer: user.id, signal: lifetime.current?.signal,
      body: { action, group_id: destination.id, source_ids: chosen } }),
      action === 'move_to_group' ? `已移动 ${chosen.length} 个频道到“${destination.name}”` : action === 'add_to_group' ? '已加入目标分组' : '已移出当前分组，订阅保持不变', () => setSelected([]), true)
  }
  const reconcileBulk = async () => {
    if (reconciling.current || !lifetime.current || lifetime.current.signal.aborted) return
    reconciling.current = true; setReloadPending(true); setReloadFailed(false)
    try {
      const results = await config.retry()
      if (!lifetime.current || lifetime.current.signal.aborted) return
      if (results.length !== 2 || !results.every(result => result.isSuccess)) { setReloadFailed(true); return }
      bulkBlocked.current = false; setUncertainBulk(false); mutation.reset()
      if (user) clearBulkUncertain(user.id)
      setNotice('已重新读取分组与订阅，请核对结果后再继续修改。')
    } catch { if (lifetime.current && !lifetime.current.signal.aborted) setReloadFailed(true) }
    finally { reconciling.current = false; if (lifetime.current && !lifetime.current.signal.aborted) setReloadPending(false) }
  }
  const closeEditor = () => { if (!submitting.current) setEditor(null) }
  const closeDeleting = () => { if (!submitting.current) setDeleting(null) }
  return <div className="workspace-page">
    <header className="workspace-page-heading"><div><p className="workspace-eyebrow">按你的方式阅读</p><h1>分组管理</h1><p>同一频道可以属于多个分组；移出分组不会取消订阅。</p></div>
      <div className="workspace-actions"><Link className="workspace-button secondary" to="/channels/smart"><Sparkles size={16} aria-hidden="true" />智能整理</Link>
        <Button className="workspace-button" type="button" disabled={!!user && !writable} onClick={() => user ? setEditor({ id: null, name: '' }) : setLogin(true)}><Plus size={16} aria-hidden="true" />新建分组</Button></div></header>
    {!user && !loading && <div className="workspace-empty"><h2>建立自己的阅读分组</h2><p>登录后，分组与订阅会随账号同步。</p><Button type="button" className="workspace-button" onClick={() => setLogin(true)}>登录</Button></div>}
    {user && (loading || !config.ready) && !config.error && <p role="status">正在读取分组…</p>}
    {config.error && <p role="alert" className="workspace-error">分组加载失败。<Button type="button" onClick={() => void config.retry()}>重试</Button></p>}
    {notice && <p role="status" className="workspace-notice">{notice}</p>}
    {uncertainBulk && <div role="alert" className="workspace-error"><p>批量操作结果尚未确认，已暂停所有修改；选择保持不变。</p>
      <Button type="button" variant="outline" disabled={reloadPending} onClick={() => void reconcileBulk()}>重新读取分组与订阅</Button>
      {reloadFailed && <p>重新读取失败，仍暂停所有修改。</p>}
    </div>}
    {mutation.isError && <p role="alert" className="workspace-error">操作未确认成功，请刷新分组核对结果后再重试。</p>}
    {user && config.ready && !config.error && <>
      <div className="workspace-group-cards">{groups.map(item => <Button key={item.id} type="button" variant="outline" className="workspace-group-card h-auto min-w-0 whitespace-normal text-foreground" disabled={uncertainBulk} aria-pressed={group?.id === item.id}
        onClick={() => { setParams({ group: String(item.id) }); setSelected([]) }}><FolderOpen size={23} aria-hidden="true" /><strong className="min-w-0 whitespace-normal break-words [overflow-wrap:anywhere]">{item.name}</strong><span>{item.source_ids.length} 个频道</span></Button>)}
        <Button type="button" variant="outline" className="workspace-group-card add h-auto whitespace-normal text-foreground" disabled={!writable} onClick={() => setEditor({ id: null, name: '' })}><Plus size={23} aria-hidden="true" /><strong>新建分组</strong><span>创建一个阅读主题</span></Button></div>
      {group ? <section className="workspace-panel">
        <header className="workspace-panel-heading"><div><h2>{group.name}</h2><p className="workspace-caption">已加入 {group.source_ids.length} 个频道</p></div><div className="workspace-actions">
          <Link className="workspace-button secondary" to={'/?scope=group&group_id=' + group.id}>阅读此分组</Link>
          <Button type="button" variant="ghost" size="icon" className="workspace-icon text-muted-foreground hover:text-foreground" disabled={!writable} aria-label="重命名分组" onClick={() => setEditor({ id: group.id, name: group.name })}><Pencil size={17} aria-hidden="true" /></Button>
          <Button type="button" variant="ghost" size="icon" className="workspace-icon text-muted-foreground hover:text-foreground" disabled={!writable} aria-label="删除分组" onClick={() => setDeleting(group.id)}><Trash2 size={17} aria-hidden="true" /></Button></div></header>
        <div className="workspace-filter-toolbar"><Input type="search" disabled={uncertainBulk} aria-label="搜索已订阅频道" placeholder="搜索已订阅频道…" value={search} onChange={event => { setSearch(event.target.value); setSelected([]) }} />
          <NativeSelect disabled={uncertainBulk} aria-label="频道范围" value={sourceFilter} onChange={event => { setSourceFilter(event.target.value); setSelected([]) }}>
            <option value="all">全部订阅</option><option value="current">当前分组</option><option value="ungrouped">未加入分组</option>
          </NativeSelect></div>
        {chosen.length > 0 && <div className="workspace-bulk-bar flex-wrap"><strong>已选 {chosen.length} 个频道</strong>
          <div className="w-full min-w-0 sm:w-64"><ModelCombobox label="目标分组" placeholder="选择目标分组" searchLabel="搜索目标分组" searchPlaceholder="搜索分组名称…" emptyText="没有匹配的分组。" wrapLabels
            value={String(targetGroup?.id ?? '')} onChange={setTargetId} disabled={!writable} options={groups.map(item => ({ value: String(item.id), label: item.name }))} /></div>
          <Button variant="outline" type="button" disabled={!writable || catalog.isError} onClick={() => bulk('add_to_group')}>加入目标分组</Button>
          <Button variant="outline" type="button" disabled={!writable || catalog.isError} onClick={() => bulk('move_to_group')}>移动到目标分组</Button>
          <Button variant="outline" type="button" disabled={!writable || catalog.isError} onClick={() => bulk('remove_from_group')}>移出当前分组</Button>
          <p className="w-full text-xs text-muted-foreground">移动会移出所选频道的其他分组；移出分组始终保留订阅。</p>
        </div>}
        {catalog.isError && <p role="alert" className="workspace-error">频道加载失败。<Button type="button" onClick={() => void catalog.refetch()}>重试</Button></p>}
        <div className="workspace-group-sources">{sources.map(source => <label key={source.id} className="workspace-group-source"><Input className="size-4 shrink-0" type="checkbox" disabled={uncertainBulk} aria-label={'选择 ' + source.name} checked={selected.includes(source.id)} onChange={event => setSelected(current => event.target.checked ? [...current, source.id] : current.filter(id => id !== source.id))} /><ChannelMark source={source} /><span><strong>{source.name}</strong><TopicTags keys={source.topics} topics={catalog.data?.topics ?? []} /></span><small>{group.source_ids.includes(source.id) ? '已加入' : '未加入'}</small></label>)}</div>
        {!catalog.isPending && !catalog.isError && !sources.length && <div className="workspace-empty"><p>{subscriptions.size ? '没有匹配的频道，可切换为“全部订阅”来添加成员。' : '还没有订阅频道。'}</p><Link className="workspace-button secondary" to="/channels">选择频道</Link></div>}
      </section> : <div className="workspace-empty"><h2>还没有分组</h2><p>创建一个分组，或使用智能整理生成可编辑的分组建议。</p></div>}
    </>}
    {login && <AuthModal onClose={() => setLogin(false)} />}
    {editor && <WorkspaceModal title={editor.id === null ? '新建分组' : '重命名分组'} busy={mutation.isPending} onClose={closeEditor}>
      <form onSubmit={event => { event.preventDefault(); const name = editor.name.trim(); if (!name) return
        run(() => editor.id === null ? createChannelGroup(name) : updateChannelGroup(editor.id, { name }), '分组已保存', value => {
          if (isRecord(value) && typeof value.id === 'number') setParams({ group: String(value.id) })
          setEditor(null); setSelected([])
        })
      }}><label>分组名称<Input autoFocus required maxLength={40} value={editor.name} disabled={mutation.isPending} onChange={event => setEditor({ ...editor, name: event.target.value })} /></label>
        {mutation.isError && <p role="alert" className="workspace-error">保存请求未确认成功。结果可能已写入，请先刷新分组确认，再决定是否重试。</p>}
        {mutation.isPending && <p role="status" className="workspace-caption">正在保存，请等待完成后关闭。</p>}
        <footer className="workspace-modal-actions"><Button type="button" variant="outline" className="workspace-button secondary" disabled={mutation.isPending} onClick={closeEditor}>{mutation.isError ? '关闭编辑' : '取消'}</Button><Button className="workspace-button" disabled={!writable || !editor.name.trim()}>{mutation.isPending ? '保存中…' : '保存'}</Button></footer></form>
    </WorkspaceModal>}
    {deleting !== null && <WorkspaceModal title="删除分组" busy={mutation.isPending} onClose={closeDeleting}><p>删除“{groups.find(item => item.id === deleting)?.name}”分组？频道订阅与其他分组均会保留。</p>
      {mutation.isError && <p role="alert" className="workspace-error">删除请求未确认成功。请先刷新分组确认结果，再决定是否重试。</p>}
      {mutation.isPending && <p role="status" className="workspace-caption">正在删除，请等待完成后关闭。</p>}
      <footer className="workspace-modal-actions"><Button type="button" variant="outline" className="workspace-button secondary" disabled={mutation.isPending} onClick={closeDeleting}>{mutation.isError ? '关闭提示' : '取消'}</Button><Button type="button" className="workspace-button danger" disabled={!writable} onClick={() => run(() => deleteChannelGroup(deleting), '分组已删除，订阅保持不变', () => { setDeleting(null); setParams({}); setSelected([]) })}>{mutation.isPending ? '删除中…' : '确认删除'}</Button></footer>
    </WorkspaceModal>}
  </div>
}
