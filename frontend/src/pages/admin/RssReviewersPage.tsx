import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import AdminLayout from '@/components/admin/AdminLayout'
import { fetchReviewers, revokeReviewer, rssReviewKey, setReviewer } from '@/services/rssReviewApi'
import type { Reviewer } from '@/services/rssReviewApi'
import { workspaceError } from '@/services/workspaceApi'
import './rssChannels.css'
export default function RssReviewersPage() {
  const { user } = useAuth()
  return user?.isSuperuser ? <ReviewerSession key={user.id} viewer={user.id} /> : <p role="alert">需要超级管理员权限。</p>
}
function ReviewerSession({ viewer }: { viewer: number }) {
  const [input, setInput] = useState(''); const [search, setSearch] = useState(''); const [page, setPage] = useState(1)
  const client = useQueryClient(); const key = useRef(crypto.randomUUID())
  const list = useQuery({ queryKey: [...rssReviewKey(viewer), 'reviewers', page], queryFn: ({ signal }) => fetchReviewers(`page=${page}`, signal), retry: false })
  const lookup = useQuery({ queryKey: [...rssReviewKey(viewer), 'reviewer-lookup', search], queryFn: ({ signal }) => fetchReviewers('username=' + encodeURIComponent(search), signal), enabled: !!search, retry: false })
  const action = useMutation({ retry: false, mutationFn: ({ row, active }: { row: Reviewer; active: boolean }) => active ? setReviewer(viewer, { username: row.username, expected_version: row.version }, key.current) : revokeReviewer(viewer, row.id!, row.version!, key.current),
    onSuccess: () => { key.current = crypto.randomUUID(); void client.invalidateQueries({ queryKey: rssReviewKey(viewer) }) } })
  return <AdminLayout><section className="rss-channel-verification"><h1>频道审核员</h1><p>审核员可处理公共推荐和频道核验。私人订阅、运行设置与其他管理权限保持独立。</p>
    <form className="rss-review-search" onSubmit={e => { e.preventDefault(); key.current = crypto.randomUUID(); action.reset(); setSearch(input.trim()) }}><label>准确用户名<input required maxLength={150} value={input} onChange={e => setInput(e.target.value)} /></label><button className="workspace-button secondary">查找账号</button></form>
    {lookup.isFetching && <p role="status">正在查找账号…</p>}{search && lookup.data?.length === 0 && <p>没有匹配的可授权账号。</p>}
    {lookup.data?.map(row => <section className="rss-addition-row" key={row.username}><h2>确认账号：{row.username}</h2><p>{row.active ? '已具有频道审核权限' : '将授予该账号频道审核权限，可随时撤销。'}</p>{!row.active && <button className="workspace-button" disabled={action.isPending} onClick={() => action.mutate({ row, active: true })}>确认授予审核权限</button>}</section>)}
    {(list.error || lookup.error || action.error) && <p role="alert">{workspaceError(list.error ?? lookup.error ?? action.error)}<button onClick={() => { void list.refetch(); if (search) void lookup.refetch() }}>重新读取授权</button></p>}
    {list.isPending && <p role="status">正在读取授权…</p>}{list.data?.length === 0 && <p>暂无审核员授权。</p>}
    {list.data?.map(row => <article className="rss-addition-row" key={row.id}><h2>{row.username}</h2><p>{row.active ? '有效审核员' : '已撤销'} · 授权版本 {row.version}</p>{row.active && <button className="workspace-button secondary" disabled={action.isPending} onClick={() => { key.current = crypto.randomUUID(); action.mutate({ row, active: false }) }}>撤销 {row.username} 的审核权限</button>}</article>)}
    <nav className="rss-pagination" aria-label="审核员分页"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} 页</span><button disabled={!list.data || list.data.length < 25} onClick={() => setPage(page + 1)}>下一页</button></nav>
  </section></AdminLayout>
}
