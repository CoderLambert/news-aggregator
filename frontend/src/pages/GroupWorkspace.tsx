import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Folder, FolderOpen, Pencil, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import AuthModal from '@/components/AuthModal'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { ChannelMark, TopicTags } from '@/components/workspace/ChannelIdentity'
import {
  createChannelGroup, createChannelGroupRoot, deleteChannelGroup, deleteChannelGroupRoot,
  updateChannelGroup, updateChannelGroupRoot,
} from '@/services/api'
import { useChannelConfig, useChannelMutation } from '@/services/channelQueries'
import { workspaceCatalogOptions, workspaceRequest } from '@/services/workspaceApi'
import { clearBulkUncertain, isBulkUncertain, markBulkUncertain } from '@/services/bulkWriteBarrier'
import { isRecord } from '@/types/news'
import { channelGroupPath, type ChannelGroup, type ChannelGroupRoot } from '@/types/channels'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { ModelCombobox } from '@/components/ui/model-combobox'

type Editor =
  | { kind: 'root'; id: number | null; name: string; version: number }
  | { kind: 'child'; id: number | null; name: string; rootId: number | null; version: number }
type Deleting = { kind: 'root'; row: ChannelGroupRoot } | { kind: 'child'; row: ChannelGroup }

export default function GroupWorkspace() {
  const { user } = useAuth()
  return <Groups key={user?.id ?? 'anonymous'} />
}

function Groups() {
  const { user, loading } = useAuth()
  const config = useChannelConfig()
  const catalog = useQuery(workspaceCatalogOptions(user?.id ?? 'anonymous', 'history'))
  const mutation = useChannelMutation()
  const submitting = useRef(false)
  const [params, setParams] = useSearchParams()
  const [login, setLogin] = useState(false)
  const [editor, setEditor] = useState<Editor | null>(null)
  const [deleting, setDeleting] = useState<Deleting | null>(null)
  const [collapsed, setCollapsed] = useState<Set<number>>(() => new Set())
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
  const roots = config.roots.data ?? []
  const groups = config.groups.data ?? []
  const requestedGroup = groups.find(item => String(item.id) === params.get('group'))
  const requestedRoot = roots.find(item => String(item.id) === params.get('root'))
  const root = requestedGroup ? roots.find(item => item.id === requestedGroup.root_id) : requestedRoot ?? roots[0]
  const group = requestedGroup ?? (!root ? groups.find(item => item.root_id === null) : undefined)
  const editedGroup = editor?.kind === 'child' && editor.id !== null ? groups.find(item => item.id === editor.id) : undefined
  const structureChanged = editor?.kind === 'child' && !!editedGroup && editedGroup.root_id !== editor.rootId
  const editedPath = editor?.kind === 'child' ? (editor.rootId === null ? editor.name.trim() : `${roots.find(item => item.id === editor.rootId)?.name ?? '未知根分类'} / ${editor.name.trim()}`) : ''
  const rootParam = params.get('root')
  const groupParam = params.get('group')
  useEffect(() => {
    if (!config.ready || config.error) return
    const next = new URLSearchParams()
    if (root) next.set('root', String(root.id))
    if (group) next.set('group', String(group.id))
    if (next.get('root') !== rootParam || next.get('group') !== groupParam) setParams(next, { replace: true })
  }, [config.ready, config.error, root, group, rootParam, groupParam, setParams])
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
    if (!user || !targetGroup || !group || !writable || catalog.isError) return
    const destination = action === 'remove_from_group' ? group : targetGroup
    run(() => workspaceRequest('/me/channel-subscriptions/', { method: 'POST', viewer: user.id, signal: lifetime.current?.signal,
      body: { action, group_id: destination.id, source_ids: chosen } }),
    action === 'move_to_group' ? `已移动 ${chosen.length} 个频道到“${channelGroupPath(destination, roots)}”` : action === 'add_to_group' ? '已加入目标分组' : '已移出当前分组，订阅保持不变', () => setSelected([]), true)
  }
  const reconcileBulk = async () => {
    if (reconciling.current || !lifetime.current || lifetime.current.signal.aborted) return
    reconciling.current = true; setReloadPending(true); setReloadFailed(false)
    try {
      const results = await config.retry()
      if (!lifetime.current || lifetime.current.signal.aborted) return
      if (results.length !== 3 || !results.every(result => result.isSuccess)) { setReloadFailed(true); return }
      bulkBlocked.current = false; setUncertainBulk(false); mutation.reset()
      if (user) clearBulkUncertain(user.id)
      setNotice('已重新读取层级、分组与订阅，请核对结果后再继续修改。')
    } catch { if (lifetime.current && !lifetime.current.signal.aborted) setReloadFailed(true) }
    finally { reconciling.current = false; if (lifetime.current && !lifetime.current.signal.aborted) setReloadPending(false) }
  }
  const selectRoot = (id: number) => { setParams({ root: String(id) }); setSelected([]) }
  const selectGroup = (row: ChannelGroup) => { setParams(row.root_id === null ? { group: String(row.id) } : { root: String(row.root_id), group: String(row.id) }); setSelected([]) }
  const closeModal = () => { if (!submitting.current) { setEditor(null); setDeleting(null) } }
  const saveEditor = () => {
    if (!editor || !editor.name.trim()) return
    const name = editor.name.trim()
    if (editor.kind === 'root') {
      run(() => editor.id === null ? createChannelGroupRoot(name) : updateChannelGroupRoot(editor.id, { name, expected_version: editor.version }), '根分类已保存', value => {
        if (isRecord(value) && typeof value.id === 'number') selectRoot(value.id)
        setEditor(null)
      })
    } else {
      run(() => editor.id === null ? createChannelGroup(name, editor.rootId) : updateChannelGroup(editor.id, {
        name, root_id: editor.rootId, expected_version: editor.version,
      }), '子分组已保存', value => {
        if (isRecord(value) && typeof value.id === 'number' && (value.root_id === null || typeof value.root_id === 'number')) {
          setParams(value.root_id === null ? { group: String(value.id) } : { root: String(value.root_id), group: String(value.id) })
        }
        setEditor(null); setSelected([])
      })
    }
  }
  const confirmDelete = () => {
    if (!deleting) return
    if (deleting.kind === 'root') {
      run(() => deleteChannelGroupRoot(deleting.row.id, deleting.row.version), '空根分类已删除', () => { setDeleting(null); setParams({}); setSelected([]) })
    } else {
      run(() => deleteChannelGroup(deleting.row.id), '子分组已删除，订阅保持不变', () => { setDeleting(null); setParams(deleting.row.root_id === null ? {} : { root: String(deleting.row.root_id) }); setSelected([]) })
    }
  }
  return <div className="workspace-page min-w-0 overflow-x-hidden">
    <header className="workspace-page-heading"><div><p className="workspace-eyebrow">按你的方式阅读</p><h1>分组层级</h1><p>可直接创建个人分组，也可在根分类下组织子分组；频道成员与阅读范围属于分组。</p></div>
      <div className="workspace-actions"><Link className="workspace-button secondary" to="/channels/smart"><Sparkles size={16} aria-hidden="true" />智能整理</Link>
        <Button type="button" disabled={!!user && !writable} onClick={() => user ? setEditor({ kind: 'child', id: null, name: '', rootId: null, version: 1 }) : setLogin(true)}><Plus size={16} aria-hidden="true" />新建分组</Button>
        <Button className="workspace-button" type="button" disabled={!!user && !writable} onClick={() => user ? setEditor({ kind: 'root', id: null, name: '', version: 1 }) : setLogin(true)}><Plus size={16} aria-hidden="true" />新建根分类</Button></div></header>
    {!user && !loading && <div className="workspace-empty"><h2>建立自己的阅读分组</h2><p>登录后，分组与订阅会随账号同步。</p><Button type="button" className="workspace-button" onClick={() => setLogin(true)}>登录</Button></div>}
    {user && (loading || !config.ready) && !config.error && <p role="status">正在读取分组层级…</p>}
    {config.error && <p role="alert" className="workspace-error">分组层级加载失败。<Button type="button" onClick={() => void config.retry()}>重试</Button></p>}
    {notice && <p role="status" className="workspace-notice">{notice}</p>}
    {uncertainBulk && <div role="alert" className="workspace-error"><p>批量操作结果尚未确认，已暂停所有修改；选择保持不变。</p>
      <Button type="button" variant="outline" disabled={reloadPending} onClick={() => void reconcileBulk()}>重新读取层级、分组与订阅</Button>
      {reloadFailed && <p>重新读取失败，仍暂停所有修改。</p>}
    </div>}
    {mutation.isError && <p role="alert" className="workspace-error">操作未确认成功，请刷新层级核对结果后再重试。</p>}
    {user && config.ready && !config.error && <div className="grid min-w-0 gap-4 md:grid-cols-[minmax(14rem,20rem)_minmax(0,1fr)]">
      <nav aria-label="分组层级" className="workspace-panel min-w-0 self-start p-3">
        {groups.filter(item => item.root_id === null).map(item => <Button key={item.id} type="button" variant={group?.id === item.id ? 'secondary' : 'ghost'}
          className="h-auto w-full min-w-0 justify-start whitespace-normal text-left" onClick={() => selectGroup(item)}><Folder size={16} className="shrink-0" aria-hidden="true" /><span className="break-words [overflow-wrap:anywhere]">{item.name}</span><span className="ml-auto text-xs text-muted-foreground">{item.source_ids.length}</span></Button>)}
        {roots.map(item => {
          const children = groups.filter(child => child.root_id === item.id)
          const isCollapsed = collapsed.has(item.id)
          return <div key={item.id} className="min-w-0">
            <div className="flex min-w-0 items-center gap-1">
              <Button type="button" size="icon" variant="ghost" aria-label={(isCollapsed ? '展开 ' : '折叠 ') + item.name} aria-expanded={!isCollapsed}
                onClick={() => setCollapsed(current => {
                  const next = new Set(current)
                  if (next.has(item.id)) next.delete(item.id)
                  else next.add(item.id)
                  return next
                })}>
                {isCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
              </Button>
              <Button type="button" variant={root?.id === item.id && !group ? 'secondary' : 'ghost'} className="h-auto min-w-0 flex-1 justify-start whitespace-normal text-left"
                onClick={() => selectRoot(item.id)}>{isCollapsed ? <Folder size={16} className="shrink-0" aria-hidden="true" /> : <FolderOpen size={16} className="shrink-0" aria-hidden="true" />}<span className="break-words [overflow-wrap:anywhere]">{item.name}</span><span className="ml-auto text-xs text-muted-foreground">{children.length}</span></Button>
            </div>
            {!isCollapsed && <div className="ml-8 border-l pl-2">{children.map(child => <Button key={child.id} type="button" variant={group?.id === child.id ? 'secondary' : 'ghost'}
              className="h-auto w-full min-w-0 justify-start whitespace-normal text-left" onClick={() => selectGroup(child)}><Folder size={16} className="shrink-0" aria-hidden="true" /><span className="break-words [overflow-wrap:anywhere]">{child.name}</span><span className="ml-auto text-xs text-muted-foreground">{child.source_ids.length}</span></Button>)}</div>}
          </div>
        })}
        {!roots.length && <p className="workspace-caption">还没有根分类。</p>}
      </nav>
      <div className="min-w-0">
        {root && !group && <section className="workspace-panel min-w-0">
          <header className="workspace-panel-heading"><div><h2>{root.name}</h2><p className="workspace-caption">{root.child_count} 个子分组；根分类不是阅读范围。</p></div><div className="workspace-actions">
            <Button type="button" onClick={() => setEditor({ kind: 'child', id: null, name: '', rootId: root.id, version: 1 })} disabled={!writable}><Plus size={16} />新建子分组</Button>
            <Button type="button" variant="ghost" size="icon" aria-label="重命名根分类" disabled={!writable} onClick={() => setEditor({ kind: 'root', id: root.id, name: root.name, version: root.version })}><Pencil size={17} /></Button>
            <Button type="button" variant="ghost" size="icon" aria-label="删除空根分类" disabled={!writable || root.child_count > 0} onClick={() => setDeleting({ kind: 'root', row: root })}><Trash2 size={17} /></Button>
          </div></header>
          {groups.filter(item => item.root_id === root.id).length ? <ul className="space-y-2">{groups.filter(item => item.root_id === root.id).map(child => <li key={child.id}><Button type="button" variant="outline" className="h-auto w-full min-w-0 justify-start whitespace-normal text-left" onClick={() => selectGroup(child)}><Folder size={16} className="shrink-0" aria-hidden="true" /><span className="min-w-0 break-words [overflow-wrap:anywhere]">{child.name}</span><span className="ml-auto shrink-0">{child.source_ids.length} 个频道</span></Button></li>)}</ul> : <div className="workspace-empty"><p>这个根分类还没有子分组。</p></div>}
        </section>}
        {group && <section className="workspace-panel min-w-0">
          <header className="workspace-panel-heading"><div><h2>{channelGroupPath(group, roots)}</h2><p className="workspace-caption">已加入 {group.source_ids.length} 个频道</p></div><div className="workspace-actions">
            <Link className="workspace-button secondary" to={'/?scope=group&group_id=' + group.id}>阅读此分组</Link>
            <Button type="button" variant="ghost" size="icon" disabled={!writable} aria-label="编辑子分组" onClick={() => setEditor({ kind: 'child', id: group.id, name: group.name, rootId: group.root_id, version: group.version })}><Pencil size={17} /></Button>
            <Button type="button" variant="ghost" size="icon" disabled={!writable} aria-label="删除子分组" onClick={() => setDeleting({ kind: 'child', row: group })}><Trash2 size={17} /></Button></div></header>
          <div className="workspace-filter-toolbar"><Input type="search" disabled={uncertainBulk} aria-label="搜索已订阅频道" placeholder="搜索已订阅频道…" value={search} onChange={event => { setSearch(event.target.value); setSelected([]) }} />
            <NativeSelect disabled={uncertainBulk} aria-label="频道范围" value={sourceFilter} onChange={event => { setSourceFilter(event.target.value); setSelected([]) }}><option value="all">全部订阅</option><option value="current">当前分组</option><option value="ungrouped">未加入分组</option></NativeSelect></div>
          {chosen.length > 0 && <div className="workspace-bulk-bar flex-wrap"><strong>已选 {chosen.length} 个频道</strong>
            <div className="w-full min-w-0 sm:w-64"><ModelCombobox label="目标子分组" placeholder="选择目标子分组" searchLabel="搜索目标子分组" searchPlaceholder="搜索分类路径…" emptyText="没有匹配的子分组。" wrapLabels
              value={String(targetGroup?.id ?? '')} onChange={setTargetId} disabled={!writable} options={groups.map(item => ({ value: String(item.id), label: channelGroupPath(item, roots) }))} /></div>
            <Button variant="outline" type="button" disabled={!writable || catalog.isError} onClick={() => bulk('add_to_group')}>加入目标分组</Button>
            <Button variant="outline" type="button" disabled={!writable || catalog.isError} onClick={() => bulk('move_to_group')}>移动到目标分组</Button>
            <Button variant="outline" type="button" disabled={!writable || catalog.isError} onClick={() => bulk('remove_from_group')}>移出当前分组</Button>
            <p className="w-full text-xs text-muted-foreground">移动会移出所选频道的其他子分组；移出分组始终保留订阅。</p>
          </div>}
          {catalog.isError && <p role="alert" className="workspace-error">频道加载失败。<Button type="button" onClick={() => void catalog.refetch()}>重试</Button></p>}
          <div className="workspace-group-sources">{sources.map(source => <label key={source.id} className="workspace-group-source"><Input className="size-4 shrink-0" type="checkbox" disabled={uncertainBulk} aria-label={'选择 ' + source.name} checked={selected.includes(source.id)} onChange={event => setSelected(current => event.target.checked ? [...current, source.id] : current.filter(id => id !== source.id))} /><ChannelMark source={source} /><span><strong>{source.name}</strong><TopicTags keys={source.topics} topics={catalog.data?.topics ?? []} /></span><small>{group.source_ids.includes(source.id) ? '已加入' : '未加入'}</small></label>)}</div>
          {!catalog.isPending && !catalog.isError && !sources.length && <div className="workspace-empty"><p>{subscriptions.size ? '没有匹配的频道，可切换为“全部订阅”来添加成员。' : '还没有订阅频道。'}</p><Link className="workspace-button secondary" to="/channels">选择频道</Link></div>}
        </section>}
        {!root && !group && <div className="workspace-empty"><h2>还没有分组</h2><p>可以直接创建个人分组；需要两级分类时再创建根分类。</p></div>}
      </div>
    </div>}
    {login && <AuthModal onClose={() => setLogin(false)} />}
    {editor && <WorkspaceModal title={editor.kind === 'root' ? (editor.id === null ? '新建根分类' : '重命名根分类') : (editor.rootId === null ? (editor.id === null ? '新建分组' : '编辑分组') : (editor.id === null ? '新建子分组' : '编辑子分组'))} busy={mutation.isPending} onClose={closeModal}>
      <form onSubmit={event => { event.preventDefault(); saveEditor() }}><label>{editor.kind === 'root' ? '根分类名称' : editor.rootId === null ? '分组名称' : '子分组名称'}<Input autoFocus required maxLength={40} value={editor.name} disabled={mutation.isPending} onChange={event => setEditor({ ...editor, name: event.target.value })} /></label>
        {editor.kind === 'child' && <label>所属根分类<NativeSelect aria-label="所属根分类" value={editor.rootId === null ? 'direct' : String(editor.rootId)} disabled={mutation.isPending} onChange={event => setEditor({ ...editor, rootId: event.target.value === 'direct' ? null : Number(event.target.value) })}><option value="direct">直接分组（无父分类）</option>{roots.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</NativeSelect></label>}
        {editor.kind === 'child' && <section aria-label="分组结构调整预览" className="my-3 rounded-lg border p-3 text-sm">
          <p>{editedGroup ? `${channelGroupPath(editedGroup, roots)} → ` : '新建：'}{editedPath}</p>
          {structureChanged && <p>确认后只调整这个分组的父分类；分组 ID、订阅成员和其他用户保持不变，原栏目不会自动删除。</p>}
        </section>}
        {mutation.isError && <p role="alert" className="workspace-error">保存请求未确认成功。结果可能已写入，请先刷新层级确认，再决定是否重试。</p>}
        {mutation.isPending && <p role="status" className="workspace-caption">正在保存，请等待完成后关闭。</p>}
        <footer className="workspace-modal-actions"><Button type="button" variant="outline" className="workspace-button secondary" disabled={mutation.isPending} onClick={closeModal}>{mutation.isError ? '关闭编辑' : '取消'}</Button><Button className="workspace-button" disabled={!writable || !editor.name.trim()}>{mutation.isPending ? '保存中…' : structureChanged ? '确认结构调整' : '保存'}</Button></footer></form>
    </WorkspaceModal>}
    {deleting && <WorkspaceModal title={deleting.kind === 'root' ? '删除空根分类' : '删除子分组'} busy={mutation.isPending} onClose={closeModal}><p>{deleting.kind === 'root' ? `删除空根分类“${deleting.row.name}”？` : `删除“${channelGroupPath(deleting.row, roots)}”子分组？频道订阅与其他分组均会保留。`}</p>
      {mutation.isError && <p role="alert" className="workspace-error">删除请求未确认成功。请先刷新层级确认结果，再决定是否重试。</p>}
      {mutation.isPending && <p role="status" className="workspace-caption">正在删除，请等待完成后关闭。</p>}
      <footer className="workspace-modal-actions"><Button type="button" variant="outline" className="workspace-button secondary" disabled={mutation.isPending} onClick={closeModal}>{mutation.isError ? '关闭提示' : '取消'}</Button><Button type="button" className="workspace-button danger" disabled={!writable} onClick={confirmDelete}>{mutation.isPending ? '删除中…' : '确认删除'}</Button></footer>
    </WorkspaceModal>}
  </div>
}
