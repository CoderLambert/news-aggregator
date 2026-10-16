import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { workspaceRequest, workspaceError } from '@/services/workspaceApi'
import type { ChannelGroup } from '@/types/channels'

interface Candidate { url: string; title: string; candidate_token: string }
interface Discovery { operation_id: string; state: string; candidates?: Candidate[]; error_code?: string }
interface DirectoryEntry { id: string; name: string; description: string; kind: string; public_url: string; executable: boolean; subscribed: boolean; cached_articles: { id: number; title: string }[] }
interface Operation { state: string; result: Discovery & { code?: string } }
interface SubscriptionResult { operation_id: string; state: string; subscription: { name: string } | null }
type Selection = { feed_url: string } | { candidate_token: string } | { directory_entry_id: string }
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'manual_blocked'])

export default function DiscoverDialog({ viewer, groups, onClose, onDone }: { viewer: number; groups: ChannelGroup[]; onClose: () => void; onDone: () => void }) {
  const client = useQueryClient()
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<'directory' | 'website' | 'feed'>('directory')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [groupIds, setGroupIds] = useState<number[]>([])
  const idempotency = useRef(crypto.randomUUID())
  const choose = (value: Selection) => { setSelection(value); idempotency.current = crypto.randomUUID() }
  const directory = useQuery({ queryKey: ['private', 'rss-directory', viewer, query], enabled: mode === 'directory',
    queryFn: ({ signal }) => workspaceRequest<{ results: DirectoryEntry[]; next_cursor: string | null }>(`/rss/directory/?q=${encodeURIComponent(query)}`, { signal }) })
  const resolve = useMutation({ mutationFn: (value: string) => workspaceRequest<Discovery>('/rss/discovery/resolve/', { method: 'POST', viewer, body: { input: value } }),
    onSuccess: () => setSelection(null) })
  const discovery = useQuery({ queryKey: ['private', 'rss-discovery', viewer, resolve.data?.operation_id],
    enabled: !!resolve.data?.operation_id && !terminal.has(resolve.data.state),
    queryFn: ({ signal }) => workspaceRequest<Operation>(`/me/rss-operations/${resolve.data!.operation_id}/`, { signal }),
    refetchInterval: result => result.state.data && terminal.has(result.state.data.state) ? false : 1500 })
  const result = discovery.data?.result ?? resolve.data
  const subscribe = useMutation({ mutationFn: (selected: Selection) => workspaceRequest<SubscriptionResult>('/me/rss-subscriptions/', {
    method: 'POST', viewer, idempotencyKey: idempotency.current, body: { ...selected, group_ids: groupIds },
  }), onSuccess: () => { void client.invalidateQueries({ queryKey: ['channels'] }); void client.invalidateQueries({ queryKey: ['workspace'] }); void client.invalidateQueries({ queryKey: ['private', 'rss-subscriptions', viewer] }) } })
  const connection = useQuery({ queryKey: ['private', 'rss-connection', viewer, subscribe.data?.operation_id], enabled: !!subscribe.data,
    queryFn: ({ signal }) => workspaceRequest<Operation>(`/me/rss-operations/${subscribe.data!.operation_id}/`, { signal }),
    refetchInterval: result => result.state.data && terminal.has(result.state.data.state) ? false : 1500 })
  const busy = resolve.isPending || subscribe.isPending
  const error = directory.error ?? resolve.error ?? discovery.error ?? subscribe.error ?? connection.error
  const discovering = !!resolve.data && !terminal.has(result?.state ?? 'pending')
  return <WorkspaceModal title="添加订阅" onClose={subscribe.data ? onDone : onClose} busy={busy}>
    <p className="workspace-muted">搜索公开目录，发现网站订阅，或直接添加公开 RSS 地址。</p>
    {!subscribe.data && <>
      <div className="workspace-tabs" role="group" aria-label="添加订阅方式">{([['directory', '搜索目录'], ['website', '发现网站'], ['feed', 'RSS 地址']] as const).map(([value, label]) => <button type="button" key={value} disabled={busy} aria-pressed={mode === value} onClick={() => { setMode(value); setSelection(null); resolve.reset(); setInput('') }}>{label}</button>)}</div>
      <form className="workspace-inline-form" onSubmit={event => {
        event.preventDefault(); setSelection(null)
        if (mode === 'directory') setQuery(input.trim())
        else if (mode === 'website') resolve.mutate(input.trim())
        else choose({ feed_url: input.trim() })
      }}>
        <label className="workspace-grow">{mode === 'directory' ? '来源名称或关键词' : mode === 'website' ? '网站地址' : '公开 RSS 地址'}
          <input type="text" required value={input} disabled={busy} placeholder={mode === 'directory' ? '例如：技术、科学' : 'https://example.com/feed'} onChange={event => { setInput(event.target.value); setSelection(null); resolve.reset(); subscribe.reset() }} />
        </label><button className="workspace-button" disabled={busy || !input.trim()}>{mode === 'directory' ? '搜索' : mode === 'website' ? '发现订阅' : '选择地址'}</button>
      </form>
      {mode === 'directory' && <section aria-label="目录搜索结果">
        {directory.isPending && <p role="status">正在读取目录…</p>}
        {directory.data?.results.length === 0 && <p role="status">没有匹配的来源。可以尝试网站地址或直接添加 RSS。</p>}
        {directory.data?.results.map(entry => <label className="workspace-resolved-choice" key={entry.id}>
          <input type="radio" name="rss-selection" disabled={busy || !entry.executable || entry.subscribed} checked={!!selection && 'directory_entry_id' in selection && selection.directory_entry_id === entry.id} onChange={() => choose({ directory_entry_id: entry.id })} />
          <span><strong>{entry.name}</strong><small>{entry.description}</small><small>{entry.subscribed ? '已订阅' : entry.executable ? '公开订阅' : '需要额外配置，暂不可订阅'}</small>{entry.cached_articles.map(article => <small key={article.id}>{article.title}</small>)}</span>
        </label>)}
        {directory.data?.next_cursor && <p className="workspace-caption">还有更多结果，请用更具体的关键词缩小范围。</p>}
      </section>}
      {mode === 'website' && <section aria-label="网站发现结果">
        {discovering && <p role="status">后台正在发现订阅…可以关闭窗口后重新查询此地址。</p>}
        {result?.state === 'succeeded' && !result.candidates?.length && <p role="status">未发现订阅。可以输入网站公布的 RSS 地址。</p>}
        {result && ['failed', 'manual_blocked', 'cancelled'].includes(result.state) && <p role="alert">发现未完成，请稍后重试。{result.error_code ? `（${result.error_code}）` : ''}</p>}
        {result?.candidates?.map(candidate => <label className="workspace-resolved-choice" key={candidate.url}>
          <input type="radio" name="rss-selection" checked={!!selection && 'candidate_token' in selection && selection.candidate_token === candidate.candidate_token} onChange={() => choose({ candidate_token: candidate.candidate_token })} />
          <span><strong>{candidate.title || candidate.url}</strong><small className="break-all">{candidate.url}</small></span>
        </label>)}
      </section>}
      {selection && <section><p role="status">已选择订阅，请确认分组。</p><fieldset><legend>加入我的分组（可多选）</legend>
        {groups.length ? groups.map(group => <label className="workspace-resolved-choice" key={group.id}><input type="checkbox" disabled={busy} checked={groupIds.includes(group.id)} onChange={event => { idempotency.current = crypto.randomUUID(); setGroupIds(ids => event.target.checked ? [...ids, group.id] : ids.filter(id => id !== group.id)) }} />{group.name}</label>) : <p className="workspace-caption">暂无分组，订阅后可在频道管理中整理。</p>}
      </fieldset></section>}
    </>}
    {subscribe.data && <section aria-live="polite"><p>订阅已保存：{subscribe.data.subscription?.name ?? '此订阅已取消'}</p>
      <p>{connection.data?.state === 'succeeded' ? '来源已连接，首次文章同步将在后台完成。' : connection.data && terminal.has(connection.data.state) ? '连接尚未完成，请在频道管理查看状态。' : '正在后台连接来源…'}</p></section>}
    {error && <p role="alert" className="workspace-error">{workspaceError(error)}<button type="button" onClick={() => { if (mode === 'directory') void directory.refetch(); else if (resolve.data) void discovery.refetch() }}>重新加载</button></p>}
    <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={busy} onClick={subscribe.data ? onDone : onClose}>{subscribe.data ? '完成' : '取消'}</button>
      {!subscribe.data && <button type="button" className="workspace-button" disabled={busy || !selection} onClick={() => { if (selection) subscribe.mutate(selection) }}>{subscribe.isPending ? '保存中…' : '确认订阅'}</button>}
    </footer>
  </WorkspaceModal>
}
