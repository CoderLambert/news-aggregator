import { useEffect, useRef, useState } from 'react'
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { workspaceRequest, workspaceError } from '@/services/workspaceApi'
import { fetchReviewCategories, rssReviewKey } from '@/services/rssReviewApi'
import { verificationError } from '@/services/rssAdminApi'
import { refreshRssViews } from '@/features/rss/queryRefresh'
import DirectoryChannelCard from '@/features/rss/DirectoryChannelCard'
import type { DirectoryEntry } from '@/features/rss/DirectoryChannelCard'
import { channelGroupPath, type ChannelGroup, type ChannelGroupRoot } from '@/types/channels'

interface Candidate { url: string; title: string; candidate_token: string }
interface Discovery { kind?: 'feed'; feed_url?: string; operation_id: string; state: string; candidates?: Candidate[]; error_code?: string; retryable?: boolean }
interface Operation { state: string; result: Discovery & { code?: string } }
interface SubscriptionResult { operation_id: string; state: string; subscription: { name: string } | null }
type Selection = { feed_url: string } | { candidate_token: string } | { directory_entry_id: string }
interface SubscriptionRequest { selected: Selection; groupIds: number[]; categoryId?: number; idempotencyKey: string }
interface DiscoverDialogProps { viewer: number; roots: ChannelGroupRoot[]; groups: ChannelGroup[]; onClose: () => void; onDone: () => void }
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

function DiscoverySession({ viewer, roots, groups, onClose, onDone }: DiscoverDialogProps) {
  const client = useQueryClient()
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [directoryCategory, setDirectoryCategory] = useState('')
  const [composing, setComposing] = useState(false)
  const [mode, setMode] = useState<'directory' | 'website' | 'feed'>('directory')
  const [submittedInput, setSubmittedInput] = useState('')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [groupIds, setGroupIds] = useState<number[]>([])
  const [categoryId, setCategoryId] = useState('')
  const categories = useQuery({ queryKey: [...rssReviewKey(viewer), 'categories'], queryFn: ({ signal }) => fetchReviewCategories(signal), enabled: !!selection, retry: false })
  const active = useRef(true)
  const refreshed = useRef('')
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  const idempotency = useRef(crypto.randomUUID())
  const choose = (value: Selection) => { setSelection(value); idempotency.current = crypto.randomUUID(); subscribe.reset() }
  // Keep server results in Query; only debounce the input, never a copied result list.
  useEffect(() => {
    if (composing || mode !== 'directory') return
    const timer = setTimeout(() => setQuery(input.trim()), input.trim() ? 250 : 0)
    return () => clearTimeout(timer)
  }, [input, composing, mode])
  const directoryCurrent = !composing && query === input.trim()
  const directory = useInfiniteQuery({
    queryKey: ['private', 'rss-directory', viewer, query, directoryCategory],
    enabled: mode === 'directory' && directoryCurrent && query.length <= 200,
    retry: false, staleTime: 30_000, refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
    initialPageParam: '',
    queryFn: ({ signal, pageParam }) => workspaceRequest<{ results: DirectoryEntry[]; next_cursor: string | null; categories?: { id: string; name: string }[] }>(
      `/rss/directory/?q=${encodeURIComponent(query)}${directoryCategory ? `&category=${encodeURIComponent(directoryCategory)}` : ''}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ''}`, { signal }),
    getNextPageParam: page => page.next_cursor ?? undefined,
  })
  const resultsCurrent = directoryCurrent && !directory.isPlaceholderData
  const directoryCategories = directory.data?.pages[0]?.categories ?? []
  const entries = directory.data?.pages.flatMap(page => page.results).filter(entry => !entry.subscribed) ?? []
  const subscribe = useMutation({ retry: false, mutationFn: ({ selected, groupIds: chosenGroups, categoryId: chosenCategory, idempotencyKey }: SubscriptionRequest) => workspaceRequest<SubscriptionResult>('/me/rss-subscriptions/', {
    method: 'POST', viewer, idempotencyKey, body: { ...selected, group_ids: chosenGroups, ...(chosenCategory ? { category_id: chosenCategory } : {}) },
  }), onSuccess: () => { if (active.current) void refreshRssViews(client, viewer) } })
  const resolve = useMutation({ retry: false, mutationFn: (value: string) => workspaceRequest<Discovery>('/rss/discovery/resolve/', { method: 'POST', viewer, body: { input: value } }),
    onSuccess: result => {
      if (result.kind === 'feed' && result.feed_url) { setMode('feed'); choose({ feed_url: result.feed_url }) }
      else setSelection(null)
    } })
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
  useEffect(() => {
    const id = subscribe.data?.operation_id
    const state = connection.data?.state ?? subscribe.data?.state
    if (id && state && terminal.has(state) && refreshed.current !== `${id}:${state}` && active.current) {
      refreshed.current = `${id}:${state}`
      void refreshRssViews(client, viewer)
    }
  }, [connection.data?.state, subscribe.data?.state, subscribe.data?.operation_id, client, viewer])
  const busy = resolve.isPending || subscribe.isPending
  const discovering = !!resolve.data && !terminal.has(result?.state ?? 'pending')
  return <WorkspaceModal className="rss-discover-modal" title="添加订阅" onClose={subscribe.data ? onDone : onClose} busy={busy}>
    <p className="workspace-muted">默认仅加入我的订阅，公开推荐需要另行提交。</p><p className="workspace-muted">输入关键词即显示可添加的渠道，已订阅渠道自动隐藏；网站或 RSS 地址也可点击查找订阅。</p>
    {!subscribe.data && <>
      <form className="workspace-inline-form" onSubmit={event => {
        event.preventDefault()
        if (composing) return
        const value = input.trim()
        setSubmittedInput(value)
        setSelection(null)
        subscribe.reset()
        if (/^rsshub:\/\//i.test(value)) {
          setMode('feed'); resolve.reset(); choose({ feed_url: value })
        } else if (!looksLikeWebAddress(value)) {
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
          <input type="text" value={input} disabled={busy} placeholder="输入即搜索渠道，也可粘贴 RSS 地址" onCompositionStart={() => {
            setComposing(true)
            void client.cancelQueries({ queryKey: ['private', 'rss-directory', viewer, query, directoryCategory], exact: true })
          }} onCompositionEnd={() => setComposing(false)} onChange={event => {
            if (event.target.value.trim() !== query) void client.cancelQueries({ queryKey: ['private', 'rss-directory', viewer, query, directoryCategory], exact: true })
            setMode('directory'); setInput(event.target.value); setSubmittedInput(''); setSelection(null); resolve.reset(); subscribe.reset()
          }} />
        </label><button className="workspace-button" disabled={busy}>{input.trim() ? '查找订阅' : '查看频道'}</button>
      </form>
      {mode === 'directory' && <fieldset className="rss-directory-categories" disabled={busy}>
        <legend>按领域发现频道</legend>
        <div role="group" aria-label="频道领域分类">
          {[{ id: '', name: '全部分类' }, ...directoryCategories].map(category => <button type="button" key={category.id}
            aria-pressed={directoryCategory === category.id} onClick={() => {
              if (directoryCategory === category.id) return
              void client.cancelQueries({ queryKey: ['private', 'rss-directory', viewer, query, directoryCategory], exact: true })
              setDirectoryCategory(category.id); setSelection(null); setCategoryId(''); subscribe.reset()
            }}>{category.name}</button>)}
        </div>
        <p className="workspace-caption">{directoryCategory ? directoryCategories.find(category => category.id === directoryCategory)?.name : '全部领域'} · 优先展示目录精选频道，可输入关键词进一步筛选。</p>
      </fieldset>}
      {mode === 'feed' && selection && <p className="workspace-caption">{'feed_url' in selection && /^rsshub:\/\//i.test(selection.feed_url) ? '已识别为 RSSHub 路由，将交给站点 RSSHub 实例连接；无需预先加入频道目录。' : '已识别为 RSS 地址。'}确认后由服务器校验公开 HTTPS 来源并交给 Miniflux 订阅，不会在浏览器抓取网页。</p>}
      {mode === 'directory' && <section aria-label="目录搜索结果" aria-busy={!resultsCurrent || directory.isFetching}>
        {(!resultsCurrent || directory.isLoading || (directory.isFetching && !directory.data)) && <p role="status">正在匹配渠道…</p>}
        {resultsCurrent && input.trim().length > 200 && <p role="status">搜索关键词最多 200 个字符；添加长 RSS 地址可点击查找订阅。</p>}
        {resultsCurrent && query.length <= 200 && directory.data && entries.length > 0 && <p role="status" className="workspace-caption">已显示 {entries.length} 个{query ? '匹配' : ''}渠道{directory.hasNextPage ? '，可继续加载' : ''}</p>}
        {resultsCurrent && query.length <= 200 && directory.data && entries.length === 0 && <p role="status">{directory.hasNextPage ? '当前已加载的结果没有可添加渠道，可继续加载更多。' : '没有可添加的匹配渠道，已订阅渠道已隐藏。'}</p>}
        {resultsCurrent && query.length <= 200 && entries.length > 0 && <div className="rss-directory-card-list">
          {entries.map(entry => <DirectoryChannelCard key={entry.id} entry={entry} disabled={busy}
            selected={!!selection && 'directory_entry_id' in selection && selection.directory_entry_id === entry.id}
            onSelect={() => choose({ directory_entry_id: entry.id })} />)}
        </div>}
        {resultsCurrent && query.length <= 200 && directory.hasNextPage && <button type="button" className="workspace-button secondary" disabled={busy || directory.isFetching} onClick={() => { void directory.fetchNextPage() }}>
          {directory.isFetchingNextPage ? '正在加载…' : '加载更多渠道'}
        </button>}
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
      {selection && <label>频道分类（用于首页筛选）<select aria-label="频道分类（用于首页筛选）" value={categoryId} disabled={busy} onChange={event => { setCategoryId(event.target.value); idempotency.current = crypto.randomUUID() }}><option value="">沿用原文章分类</option>{categories.data?.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}</select><small>仅影响我的频道筛选，与下方多选分组独立。</small></label>}
      {selection && <section><p role="status">已选择订阅，请确认分组。</p><fieldset><legend>加入我的子分组（最多 3 个）</legend>
        {groups.length ? groups.map(group => <label className="workspace-resolved-choice" key={group.id}><input type="checkbox" disabled={busy || (!groupIds.includes(group.id) && groupIds.length >= 3)} checked={groupIds.includes(group.id)} onChange={event => { subscribe.reset(); idempotency.current = crypto.randomUUID(); setGroupIds(ids => event.target.checked ? [...ids, group.id] : ids.filter(id => id !== group.id)) }} />{channelGroupPath(group, roots)}</label>) : <p className="workspace-caption">暂无子分组，订阅后可在频道管理中整理。</p>}
      </fieldset></section>}
    </>}
    {subscribe.data && <section aria-live="polite"><a className="workspace-link" href="/channels/additions">在添加记录中持续查看进度</a><p>{subscribe.data.subscription ? `已订阅：${subscribe.data.subscription.name}` : '连接请求已保存，验证成功后加入我的订阅'}</p>
      {connection.data?.state === 'failed' && connection.data.result?.code && <p role="alert">{verificationError(connection.data.result.code)}</p>}
      <p>{connection.error ? '暂时无法读取连接状态，请稍后核对。' : connection.data?.state === 'succeeded' ? '来源已连接，首次文章同步将在后台完成。' : connection.data && terminal.has(connection.data.state) ? '连接尚未完成，请在频道管理查看状态。' : '正在后台连接来源…'}</p></section>}
    {!subscribe.data && mode === 'directory' && resultsCurrent && query.length <= 200 && directory.error && <p role="alert" className="workspace-error">目录读取失败：{workspaceError(directory.error)}
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
      {!subscribe.data && <button type="button" className="workspace-button" disabled={busy || !selection} onClick={() => { if (selection) subscribe.mutate({ selected: selection, groupIds, ...(categoryId ? { categoryId: Number(categoryId) } : {}), idempotencyKey: idempotency.current }) }}>{subscribe.isPending ? '保存中…' : '确认订阅'}</button>}
    </footer>
  </WorkspaceModal>
}

