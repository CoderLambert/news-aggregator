import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FolderOpen, Pencil, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import AuthModal from '@/components/AuthModal'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { ChannelMark, TopicTags } from '@/components/workspace/ChannelIdentity'
import { createChannelGroup, deleteChannelGroup, updateChannelGroup } from '@/services/api'
import { useChannelConfig, useChannelMutation } from '@/services/channelQueries'
import { workspaceCatalogOptions } from '@/services/workspaceApi'
import { isRecord } from '@/types/news'

export default function GroupWorkspace() {
  const { user } = useAuth()
  return <Groups key={user?.id ?? 'anonymous'} />
}

function Groups() {
  const { user, loading } = useAuth()
  const config = useChannelConfig()
  const catalog = useQuery(workspaceCatalogOptions())
  const mutation = useChannelMutation()
  const [params, setParams] = useSearchParams()
  const [login, setLogin] = useState(false)
  const [editor, setEditor] = useState<{ id: number | null; name: string } | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [onlyMembers, setOnlyMembers] = useState(false)
  const [selected, setSelected] = useState<number[]>([])
  const [notice, setNotice] = useState('')
  const groups = config.groups.data ?? []
  const group = groups.find(item => String(item.id) === params.get('group')) ?? groups[0]
  const subscriptions = new Set((config.subscriptions.data ?? []).map(item => item.source_id))
  const sources = (catalog.data?.sources ?? []).filter(source => subscriptions.has(source.id)
    && (!onlyMembers || group?.source_ids.includes(source.id))
    && (!search.trim() || source.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())))
  const chosen = sources.filter(source => selected.includes(source.id)).map(source => source.id)
  const writable = config.enabled && config.ready && !config.error && !mutation.isPending
  const run = (perform: () => Promise<unknown>, message: string, after?: (value: unknown) => void) => {
    mutation.mutate(perform, { onSuccess: value => { setNotice(message); after?.(value) } })
  }
  return <div className="workspace-page">
    <header className="workspace-page-heading"><div><p className="workspace-eyebrow">按你的方式阅读</p><h1>分组管理</h1><p>同一频道可以属于多个分组；移出分组不会取消订阅。</p></div>
      <div className="workspace-actions"><Link className="workspace-button secondary" to="/channels/smart"><Sparkles size={16} aria-hidden="true" />智能整理</Link>
        <button className="workspace-button" type="button" disabled={!!user && !writable} onClick={() => user ? setEditor({ id: null, name: '' }) : setLogin(true)}><Plus size={16} aria-hidden="true" />新建分组</button></div></header>
    {!user && !loading && <div className="workspace-empty"><h2>建立自己的阅读分组</h2><p>登录后，分组与订阅会随账号同步。</p><button type="button" className="workspace-button" onClick={() => setLogin(true)}>登录</button></div>}
    {user && (loading || !config.ready) && !config.error && <p role="status">正在读取分组…</p>}
    {config.error && <p role="alert" className="workspace-error">分组加载失败。<button type="button" onClick={() => void config.retry()}>重试</button></p>}
    {notice && <p role="status" className="workspace-notice">{notice}</p>}
    {mutation.isError && <p role="alert" className="workspace-error">操作失败，请检查分组名称是否重复后重试。</p>}
    {user && config.ready && !config.error && <>
      <div className="workspace-group-cards">{groups.map(item => <button key={item.id} type="button" className="workspace-group-card" aria-pressed={group?.id === item.id}
        onClick={() => { setParams({ group: String(item.id) }); setSelected([]) }}><FolderOpen size={23} aria-hidden="true" /><strong>{item.name}</strong><span>{item.source_ids.length} 个频道</span></button>)}
        <button type="button" className="workspace-group-card add" disabled={!writable} onClick={() => setEditor({ id: null, name: '' })}><Plus size={23} aria-hidden="true" /><strong>新建分组</strong><span>创建一个阅读主题</span></button></div>
      {group ? <section className="workspace-panel">
        <header className="workspace-panel-heading"><div><h2>{group.name}</h2><p className="workspace-caption">已加入 {group.source_ids.length} 个频道</p></div><div className="workspace-actions">
          <Link className="workspace-button secondary" to={'/?scope=group&group_id=' + group.id}>阅读此分组</Link>
          <button type="button" className="workspace-icon" disabled={!writable} aria-label="重命名分组" onClick={() => setEditor({ id: group.id, name: group.name })}><Pencil size={17} aria-hidden="true" /></button>
          <button type="button" className="workspace-icon" disabled={!writable} aria-label="删除分组" onClick={() => setDeleting(group.id)}><Trash2 size={17} aria-hidden="true" /></button></div></header>
        <div className="workspace-filter-toolbar"><input type="search" aria-label="搜索已订阅频道" placeholder="搜索已订阅频道…" value={search} onChange={event => { setSearch(event.target.value); setSelected([]) }} />
          <label className="workspace-check"><input type="checkbox" checked={onlyMembers} onChange={event => { setOnlyMembers(event.target.checked); setSelected([]) }} />只看当前分组</label></div>
        {chosen.length > 0 && <div className="workspace-bulk-bar"><strong>已选 {chosen.length} 个</strong><button className="workspace-button secondary" type="button" disabled={!writable} onClick={() => run(() => updateChannelGroup(group.id, { add_source_ids: chosen }), '已加入当前分组', () => setSelected([]))}>加入当前分组</button><button className="workspace-button secondary" type="button" disabled={!writable} onClick={() => run(() => updateChannelGroup(group.id, { remove_source_ids: chosen }), '已移出当前分组，订阅保持不变', () => setSelected([]))}>移出当前分组</button></div>}
        {catalog.isError && <p role="alert" className="workspace-error">频道加载失败。<button type="button" onClick={() => void catalog.refetch()}>重试</button></p>}
        <div className="workspace-group-sources">{sources.map(source => <label key={source.id} className="workspace-group-source"><input type="checkbox" aria-label={'选择 ' + source.name} checked={selected.includes(source.id)} onChange={event => setSelected(current => event.target.checked ? [...current, source.id] : current.filter(id => id !== source.id))} /><ChannelMark source={source} /><span><strong>{source.name}</strong><TopicTags keys={source.topics} topics={catalog.data?.topics ?? []} /></span><small>{group.source_ids.includes(source.id) ? '已加入' : '未加入'}</small></label>)}</div>
        {!catalog.isPending && !catalog.isError && !sources.length && <div className="workspace-empty"><p>{subscriptions.size ? '没有匹配的频道，可取消“只看当前分组”来添加成员。' : '还没有订阅频道。'}</p><Link className="workspace-button secondary" to="/channels">选择频道</Link></div>}
      </section> : <div className="workspace-empty"><h2>还没有分组</h2><p>创建一个分组，或使用智能整理生成可编辑的分组建议。</p></div>}
    </>}
    {login && <AuthModal onClose={() => setLogin(false)} />}
    {editor && <WorkspaceModal title={editor.id === null ? '新建分组' : '重命名分组'} busy={mutation.isPending} onClose={() => setEditor(null)}>
      <form onSubmit={event => { event.preventDefault(); const name = editor.name.trim(); if (!name) return
        run(() => editor.id === null ? createChannelGroup(name) : updateChannelGroup(editor.id, { name }), '分组已保存', value => {
          if (isRecord(value) && typeof value.id === 'number') setParams({ group: String(value.id) })
          setEditor(null); setSelected([])
        })
      }}><label>分组名称<input autoFocus required maxLength={40} value={editor.name} disabled={mutation.isPending} onChange={event => setEditor({ ...editor, name: event.target.value })} /></label>
        {mutation.isError && <p role="alert" className="workspace-error">保存失败，名称可能已存在，请修改后重试。</p>}
        <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={mutation.isPending} onClick={() => setEditor(null)}>取消</button><button className="workspace-button" disabled={!writable || !editor.name.trim()}>保存</button></footer></form>
    </WorkspaceModal>}
    {deleting !== null && <WorkspaceModal title="删除分组" busy={mutation.isPending} onClose={() => setDeleting(null)}><p>删除“{groups.find(item => item.id === deleting)?.name}”分组？频道订阅与其他分组均会保留。</p>
      {mutation.isError && <p role="alert" className="workspace-error">删除失败，请重试。</p>}
      <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={mutation.isPending} onClick={() => setDeleting(null)}>取消</button><button type="button" className="workspace-button danger" disabled={!writable} onClick={() => run(() => deleteChannelGroup(deleting), '分组已删除，订阅保持不变', () => { setDeleting(null); setParams({}); setSelected([]) })}>确认删除</button></footer>
    </WorkspaceModal>}
  </div>
}
