import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { workspaceRequest, workspaceError } from '@/services/workspaceApi'
import type { ChannelGroup } from '@/types/channels'

interface Candidate { url: string; title: string; candidate_token: string }
interface Discovery { operation_id: string; state: string; candidates?: Candidate[]; error_code?: string; retryable?: boolean }
interface DirectoryEntry { id: string; name: string; description: string; kind: string; public_url: string; executable: boolean; subscribed: boolean; cached_articles: { id: number; title: string }[] }
interface Operation { state: string; result: Discovery & { code?: string } }
interface SubscriptionResult { operation_id: string; state: string; subscription: { name: string } | null }
type Selection = { feed_url: string } | { candidate_token: string } | { directory_entry_id: string }
interface SubscriptionRequest { selected: Selection; groupIds: number[]; idempotencyKey: string }
interface DiscoverDialogProps { viewer: number; groups: ChannelGroup[]; onClose: () => void; onDone: () => void }
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'manual_blocked'])

// Free text searches the reviewed local directory; URLs use the engine or the
// normal feed subscription path. No browser-side fetching of publisher pages.
const looksLikeFeedAddress = (value: string): boolean =>
  /(?:\/(?:feed|rss|atom)(?:[/?#.]|$)|\.(?:xml|rss|atom)(?:[?#]|$)|[?&](?:format|output)=(?:rss|atom|xml)(?:[&#]|$))/i.test(value)

const looksLikeWebAddress = (value: string): boolean =>
  /^https?:\/\//i.test(value) || /^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?::\d+)?(?:[/?#]|$)/i.test(value)

export default function DiscoverDialog(props: DiscoverDialogProps) {
  // A changed account starts a fresh intent, including any failed request that
  // could otherwise be retried with the previous account's selection or groups.
  return <DiscoverySession key={props.viewer} {...props} />
}

function DiscoverySession({ viewer, groups, onClose, onDone }: DiscoverDialogProps) {
  const client = useQueryClient()
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<'directory' | 'website' | 'feed'>('directory')
  const [submittedInput, setSubmittedInput] = useState('')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [groupIds, setGroupIds] = useState<number[]>([])
  const idempotency = useRef(crypto.randomUUID())
  const choose = (value: Selection) => { setSelection(value); idempotency.current = crypto.randomUUID(); subscribe.reset() }
  const directory = useQuery({ queryKey: ['private', 'rss-directory', viewer, query], enabled: mode === 'directory', retry: false,
    queryFn: ({ signal }) => workspaceRequest<{ results: DirectoryEntry[]; next_cursor: string | null }>(`/rss/directory/?q=${encodeURIComponent(query)}`, { signal }) })
  const subscribe = useMutation({ retry: false, mutationFn: ({ selected, groupIds: chosenGroups, idempotencyKey }: SubscriptionRequest) => workspaceRequest<SubscriptionResult>('/me/rss-subscriptions/', {
    method: 'POST', viewer, idempotencyKey, body: { ...selected, group_ids: chosenGroups },
  }), onSuccess: () => { void client.invalidateQueries({ queryKey: ['channels'] }); void client.invalidateQueries({ queryKey: ['workspace'] }); void client.invalidateQueries({ queryKey: ['private', 'rss-subscriptions', viewer] }) } })
  const resolve = useMutation({ retry: false, mutationFn: (value: string) => workspaceRequest<Discovery>('/rss/discovery/resolve/', { method: 'POST', viewer, body: { input: value } }),
    onSuccess: () => setSelection(null) })
  const discovery = useQuery({ queryKey: ['private', 'rss-discovery', viewer, resolve.data?.operation_id],
    enabled: mode === 'website' && !!resolve.data?.operation_id && !terminal.has(resolve.data.state) && !subscribe.data,
    retry: false, refetchOnWindowFocus: false,
    queryFn: ({ signal }) => workspaceRequest<Operation>(`/me/rss-operations/${resolve.data!.operation_id}/`, { signal }),
    refetchInterval: result => result.state.error || (result.state.data && terminal.has(result.state.data.state)) ? false : 1500 })
  const result = discovery.data?.result ?? resolve.data
  const connection = useQuery({ queryKey: ['private', 'rss-connection', viewer, subscribe.data?.operation_id], enabled: !!subscribe.data,
    retry: false, refetchOnWindowFocus: false,
    queryFn: ({ signal }) => workspaceRequest<Operation>(`/me/rss-operations/${subscribe.data!.operation_id}/`, { signal }),
    refetchInterval: result => result.state.error || (result.state.data && terminal.has(result.state.data.state)) ? false : 1500 })
  const busy = resolve.isPending || subscribe.isPending
  const discovering = !!resolve.data && !terminal.has(result?.state ?? 'pending')
  return <WorkspaceModal title="添加订阅" onClose={subscribe.data ? onDone : onClose} busy={busy}>
    <p className="workspace-muted">输入关键词、网站或公开 RSS 地址，自动查找可订阅来源。无需选择接入方式。</p>
    {!subscribe.data && <>
      <form className="workspace-inline-form" onSubmit={event => {
        event.preventDefault()
        const value = input.trim()
        if (!value) return
        setSubmittedInput(value)
        setSelection(null)
        subscribe.reset()
        if (!looksLikeWebAddress(value)) {
          setMode('directory')
          resolve.reset()
          setQuery(value)
        } else if (value.startsWith('https://') && looksLikeFeedAddress(value)) {
          setMode('feed')
          resolve.reset()
          choose({ feed_url: value })
        } else {
          setMode('website')
          resolve.mutate(value)
        }
      }}>
        <label className="workspace-grow">搜索订阅源、网站或 RSS 地址
          <input type="text" required value={input} disabled={busy} placeholder="GitHub、react.dev 或 https://example.com/feed.xml" onChange={event => {
            setInput(event.target.value); setSubmittedInput(''); setSelection(null); resolve.reset(); subscribe.reset()
          }} />
        </label><button className="workspace-button" disabled={busy || !input.trim()}>查找订阅</button>
      </form>
      {mode === 'feed' && selection && <p className="workspace-caption">已识别为 RSS 地址。确认后由服务器校验公开 HTTPS 来源并交给 Miniflux 订阅，不会在浏览器抓取网页。</p>}
      {mode === 'directory' && (submittedInput === input.trim()) && <section aria-label="目录搜索结果">
        {directory.isPending && <p role="status">正在读取目录…</p>}
        {directory.data?.results.length === 0 && <p role="status">没有匹配的来源。可以尝试网站地址或直接添加 RSS。</p>}
        {directory.data?.results.map(entry => <label className="workspace-resolved-choice" key={entry.id}>
          <input type="radio" name="rss-selection" disabled={busy || !entry.executable || entry.subscribed} checked={!!selection && 'directory_entry_id' in selection && selection.directory_entry_id === entry.id} onChange={() => choose({ directory_entry_id: entry.id })} />
          <span><strong>{entry.name}</strong><small>{entry.description}</small><small>{entry.subscribed ? '已订阅' : entry.executable ? '公开订阅' : '需要额外配置，暂不可订阅'}</small>{entry.cached_articles.map(article => <small key={article.id}>{article.title}</small>)}</span>
        </label>)}
        {directory.data?.next_cursor && <p className="workspace-caption">还有更多结果，请用更具体的关键词缩小范围。</p>}
      </section>}
      {mode === 'website' && <section aria-label="网站发现结果">
        {resolve.isPending && <p role="status">正在提交发现请求…</p>}
        {discovering && !discovery.error && <p role="status">后台正在发现订阅…可以关闭窗口后重新查询此地址。</p>}
        {result?.state === 'succeeded' && !result.candidates?.length && <>
          <p role="status">未发现网站声明的订阅源。可以粘贴网站公布的 RSS 地址，或明确尝试将此地址作为 Feed 添加。</p>
          <button type="button" className="workspace-button secondary" onClick={() => { setMode('feed'); choose({ feed_url: /^https?:\/\//i.test(input.trim()) ? input.trim() : 'https://' + input.trim() }) }}>
            尝试直接添加此 Feed
          </button>
        </>}
        {result && ['failed', 'manual_blocked', 'cancelled'].includes(result.state) && <p role="alert">发现未完成，请稍后重试。{result.error_code ? `（${result.error_code}）` : ''}
          {result.state === 'failed' && result.retryable && <button type="button" className="workspace-link" disabled={busy} onClick={() => resolve.mutate(submittedInput)}>重新查找订阅</button>}
        </p>}
        {result?.candidates?.map(candidate => <label className="workspace-resolved-choice" key={candidate.url}>
          <input type="radio" name="rss-selection" disabled={busy} checked={!!selection && 'candidate_token' in selection && selection.candidate_token === candidate.candidate_token} onChange={() => choose({ candidate_token: candidate.candidate_token })} />
          <span><strong>{candidate.title || candidate.url}</strong><small className="break-all">{candidate.url}</small></span>
        </label>)}
      </section>}
      {selection && <section><p role="status">已选择订阅，请确认分组。</p><fieldset><legend>加入我的分组（可多选）</legend>
        {groups.length ? groups.map(group => <label className="workspace-resolved-choice" key={group.id}><input type="checkbox" disabled={busy} checked={groupIds.includes(group.id)} onChange={event => { subscribe.reset(); idempotency.current = crypto.randomUUID(); setGroupIds(ids => event.target.checked ? [...ids, group.id] : ids.filter(id => id !== group.id)) }} />{group.name}</label>) : <p className="workspace-caption">暂无分组，订阅后可在频道管理中整理。</p>}
      </fieldset></section>}
    </>}
    {subscribe.data && <section aria-live="polite"><p>{subscribe.data.subscription ? `已订阅：${subscribe.data.subscription.name}` : '连接请求已保存，验证成功后加入我的订阅'}</p>
      <p>{connection.error ? '暂时无法读取连接状态，请稍后核对。' : connection.data?.state === 'succeeded' ? '来源已连接，首次文章同步将在后台完成。' : connection.data && terminal.has(connection.data.state) ? '连接尚未完成，请在频道管理查看状态。' : '正在后台连接来源…'}</p></section>}
    {!subscribe.data && mode === 'directory' && submittedInput === input.trim() && directory.error && <p role="alert" className="workspace-error">目录读取失败：{workspaceError(directory.error)}
      <button type="button" className="workspace-link" disabled={busy || directory.isFetching} onClick={() => { void directory.refetch({ cancelRefetch: false }) }}>重新加载目录</button>
    </p>}
    {!subscribe.data && mode === 'website' && resolve.error && <p role="alert" className="workspace-error">发现请求未完成：{workspaceError(resolve.error)}
      <button type="button" className="workspace-link" disabled={busy} onClick={() => resolve.mutate(submittedInput)}>重新查找订阅</button>
    </p>}
    {!subscribe.data && mode === 'website' && discovery.error && <p role="alert" className="workspace-error">发现结果读取失败：{workspaceError(discovery.error)}
      <button type="button" className="workspace-link" disabled={busy || discovery.isFetching} onClick={() => { void discovery.refetch({ cancelRefetch: false }) }}>重新读取发现结果</button>
    </p>}
    {!subscribe.data && subscribe.error && <p role="alert" className="workspace-error">订阅保存结果未确认：{workspaceError(subscribe.error)}
      <button type="button" className="workspace-link" disabled={busy} onClick={() => { if (subscribe.variables) subscribe.mutate(subscribe.variables) }}>重试保存订阅</button>
    </p>}
    {subscribe.data && connection.error && <p role="alert" className="workspace-error">连接状态读取失败：{workspaceError(connection.error)}
      <button type="button" className="workspace-link" disabled={connection.isFetching} onClick={() => { void connection.refetch({ cancelRefetch: false }) }}>重新读取连接状态</button>
    </p>}
    <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={busy} onClick={subscribe.data ? onDone : onClose}>{subscribe.data ? '完成' : '取消'}</button>
      {!subscribe.data && <button type="button" className="workspace-button" disabled={busy || !selection} onClick={() => { if (selection) subscribe.mutate({ selected: selection, groupIds, idempotencyKey: idempotency.current }) }}>{subscribe.isPending ? '保存中…' : '确认订阅'}</button>}
    </footer>
  </WorkspaceModal>
}

