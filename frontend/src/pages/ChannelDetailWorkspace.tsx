import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useChannelConfig, useChannelMutation } from '@/services/channelQueries'
import { changeChannelSubscriptions } from '@/services/api'
import AuthModal from '@/components/AuthModal'
import { ChannelMark, TopicTags, Availability } from '@/components/workspace/ChannelIdentity'
import { workspaceRequest, workspaceError, workspaceCatalogOptions, workspaceKeys, safeExternalUrl, originLabel, type ChannelProfile } from '@/services/workspaceApi'

export default function ChannelDetailWorkspace() {
  const { id } = useParams()
  const { user } = useAuth()
  return <Profile key={id + ':' + (user?.id ?? 'anonymous')} id={Number(id)} />
}

function Profile({ id }: { id: number }) {
  const { user } = useAuth()
  const config = useChannelConfig()
  const mutation = useChannelMutation()
  const client = useQueryClient()
  const viewer = user?.id ?? 'anonymous'
  const catalog = useQuery(workspaceCatalogOptions(user?.id ?? 'anonymous', 'history'))
  const profile = useQuery({ queryKey: ['workspace', viewer, 'source', id], enabled: Number.isSafeInteger(id) && id > 0,
    queryFn: ({ signal }) => workspaceRequest<ChannelProfile>('/smart-channels/sources/' + id + '/', { signal }) })
  const [login, setLogin] = useState(false)
  const [edit, setEdit] = useState<{ description: string; topics: string[] } | null>(null)
  const save = useMutation({ mutationFn: (body: { description: string; topics: string[] }) => workspaceRequest<ChannelProfile>('/smart-channels/sources/' + id + '/', { method: 'PATCH', body }),
    onSuccess: () => { setEdit(null); void client.invalidateQueries({ queryKey: workspaceKeys.all }) } })
  const source = profile.data
  const subscription = (config.subscriptions.data ?? []).find(item => item.source_id === id)
  const memberNames = (config.groups.data ?? []).filter(group => subscription?.group_ids.includes(group.id)).map(group => group.name)
  if (!Number.isSafeInteger(id) || id <= 0) return <div className="workspace-empty"><h1>无效的频道地址</h1><Link to="/channels">返回频道管理</Link></div>
  return <div className="workspace-page">
    <Link className="workspace-back-link" to="/channels"><ArrowLeft size={16} aria-hidden="true" />返回频道管理</Link>
    {profile.isPending && <p role="status" className="workspace-empty">正在读取频道资料…</p>}
    {profile.isError && <p role="alert" className="workspace-error">{workspaceError(profile.error)} <button type="button" onClick={() => void profile.refetch()}>重试</button></p>}
    {source && <>
      <header className="workspace-profile-heading"><ChannelMark source={source} /><div><h1>{source.name}</h1><p>{source.description || '暂无经过确认的频道简介。'}</p><TopicTags keys={source.topics} topics={catalog.data?.topics ?? []} /></div>
        {config.accounts && <button type="button" className={'workspace-button ' + (subscription ? 'subscribed' : '')} disabled={!!subscription || mutation.isPending || (!!user && (!config.ready || config.error)) || source.subscription_status !== 'active'}
          onClick={() => user ? mutation.mutate(() => changeChannelSubscriptions({ action: 'subscribe', source_ids: [id] })) : setLogin(true)}>{subscription ? '✓ 已订阅' : '+ 订阅频道'}</button>}
      </header>
      {mutation.isError && <p role="alert" className="workspace-error">订阅失败，请重试。</p>}
      <div className="workspace-profile-layout"><div>
        <section className="workspace-panel"><header className="workspace-panel-heading"><h2>频道资料</h2>{user?.isSuperuser && <button type="button" className="workspace-link" onClick={() => setEdit({ description: source.description, topics: [...source.topics] })}>编辑元信息</button>}</header>
          <dl className="workspace-metadata"><div><dt>地区 / 语言</dt><dd>{source.region === 'domestic' ? '国内' : '国际'} / {source.language === 'zh' ? '中文' : source.language === 'en' ? '英文' : source.language}</dd></div>
            <div><dt>来源类型</dt><dd>{{ news: '新闻媒体', aggregator: '聚合平台', discussion: '讨论社区' }[source.source_type] ?? source.source_type}</dd></div>
            <div><dt>主题依据</dt><dd>{originLabel[source.origin] ?? source.origin}</dd></div>
            <div><dt>内容范围</dt><dd>{source.reading_policy === 'rss_summary_only' ? '仅 RSS 标题、摘要与原文链接' : source.reading_policy === 'public_rss' ? 'RSS 公开提供的内容' : '按来源授权策略收录'}</dd></div>
            <div><dt>收录资讯</dt><dd>{source.news_count} 篇</dd></div><div><dt>元信息更新</dt><dd>{source.updated_at ? new Date(source.updated_at).toLocaleString() : '使用已登记频道资料'}</dd></div>
            <div><dt>来源网站</dt><dd>{safeExternalUrl(source.url) ? <a href={safeExternalUrl(source.url)} target="_blank" rel="noopener noreferrer">{source.url}<ExternalLink size={12} aria-hidden="true" /></a> : '未登记'}</dd></div>
            <div><dt>RSS</dt><dd>{source.feed_url && safeExternalUrl(source.feed_url) ? <a href={safeExternalUrl(source.feed_url)} target="_blank" rel="noopener noreferrer">{source.feed_url}</a> : '使用其他已登记接入方式'}</dd></div>
          </dl><Availability source={source} />
          {source.needs_review && <p className="workspace-soft-panel">主题尚待确认，不会仅凭 AI 建议覆盖你的个人分组。</p>}
          {edit && <form className="workspace-soft-panel" onSubmit={event => { event.preventDefault(); save.mutate(edit) }}>
            <label>频道简介<textarea value={edit.description} maxLength={1000} rows={3} disabled={save.isPending} onChange={event => setEdit({ ...edit, description: event.target.value })} /></label>
            <fieldset className="workspace-group-checkboxes"><legend>已审核主题</legend>{(catalog.data?.topics ?? []).map(topic => <label key={topic.key}><input type="checkbox" checked={edit.topics.includes(topic.key)} disabled={save.isPending} onChange={event => setEdit({ ...edit, topics: event.target.checked ? [...edit.topics, topic.key] : edit.topics.filter(key => key !== topic.key) })} />{topic.name}</label>)}</fieldset>
            {save.isError && <p role="alert" className="workspace-error">{workspaceError(save.error)}</p>}
            <div className="workspace-actions"><button type="button" className="workspace-button secondary" disabled={save.isPending} onClick={() => setEdit(null)}>取消</button><button className="workspace-button" disabled={save.isPending}>保存审核资料</button></div>
          </form>}
        </section>
        <section className="workspace-panel"><header className="workspace-panel-heading"><h2>最近收录</h2><Link className="workspace-link" to={'/?scope=all&source=' + id}>查看全部 →</Link></header>
          <ul className="workspace-recent-stories">{(source.recent_articles ?? []).map(article => <li key={article.id}><Link to={'/news/' + article.id}>{article.title}</Link><time dateTime={article.publish_time}>{new Date(article.publish_time).toLocaleDateString()}</time></li>)}</ul>
          {!source.recent_articles?.length && <p className="workspace-muted">尚无已收录文章。订阅不保证立即产生内容。</p>}
        </section>
      </div><aside><section className="workspace-panel"><h2>我的分组</h2><p className="workspace-muted">{subscription ? memberNames.length ? memberNames.join('、') : '已订阅，尚未加入分组。' : '订阅后可将该频道加入个人分组。'}</p>
        {subscription && <Link className="workspace-button secondary" to="/channels/groups">调整分组</Link>}
        {config.enabled && <Link className="workspace-link" to="/channels/smart">使用智能整理 →</Link>}
      </section></aside></div>
    </>}
    {login && <AuthModal onClose={() => setLogin(false)} />}
  </div>
}
