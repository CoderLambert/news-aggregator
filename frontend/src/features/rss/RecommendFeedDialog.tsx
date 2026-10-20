import { useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { changeRecommendation, fetchReviewCategories, registerPublicSource, submitRecommendation } from '@/services/rssReviewApi'
import type { Recommendation } from '@/services/rssReviewApi'
import { workspaceError } from '@/services/workspaceApi'

export default function RecommendFeedDialog({ viewer, sourceId, initial, onClose, onDone }: { viewer: number; sourceId?: number; initial?: Recommendation; onClose: () => void; onDone: () => void }) {
  const admin = sourceId === undefined && !initial
  const [name, setName] = useState(initial?.name ?? ''); const [url, setUrl] = useState(''); const [category, setCategory] = useState(initial ? String(initial.category_id) : '')
  const [language, setLanguage] = useState(initial?.language ?? 'zh'); const [note, setNote] = useState(initial?.note ?? ''); const [consent, setConsent] = useState(false)
  const key = useRef(crypto.randomUUID())
  const categories = useQuery({ queryKey: ['private', 'rss-review', viewer, 'categories'], queryFn: ({ signal }) => fetchReviewCategories(signal), retry: false })
  const save = useMutation({ retry: false, mutationFn: () => {
    const data = { name: name.trim(), category_id: Number(category), language }
    if (initial) return changeRecommendation(viewer, initial.submission_id!, { ...data, action: 'resubmit', expected_version: initial.version, source_id: sourceId, note, confirm_public_scope: consent }, key.current)
    return admin ? registerPublicSource(viewer, { ...data, feed_url: url.trim() }, key.current) : submitRecommendation(viewer, { ...data, source_id: sourceId, note, confirm_public_scope: consent }, key.current)
  }, onSuccess: onDone })
  const change = () => { key.current = crypto.randomUUID(); save.reset() }
  return <WorkspaceModal title={admin ? '新增公共频道' : initial ? '更正后重提' : '推荐到公共频道'} onClose={onClose} busy={save.isPending}>
    <form onSubmit={event => { event.preventDefault(); save.mutate() }} className="rss-public-form">
      <p>公开范围：公开 Feed 最近七天内经验证的文章及后续文章。个人订阅分组、阅读和 AI 记录保持私有。</p>
      <label>频道名称<input required maxLength={255} value={name} onChange={e => { change(); setName(e.target.value) }} disabled={save.isPending} /></label>
      {admin && <label>公开 RSS 地址<input required type="url" maxLength={1024} placeholder="https://example.com/feed.xml" value={url} onChange={e => { change(); setUrl(e.target.value) }} disabled={save.isPending} /></label>}
      <label>分类<select required value={category} onChange={e => { change(); setCategory(e.target.value) }} disabled={save.isPending}><option value="">请选择</option>{categories.data?.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <label>语言<select value={language} onChange={e => { change(); setLanguage(e.target.value) }} disabled={save.isPending}><option value="zh">中文</option><option value="en">英文</option><option value="other">其他</option></select></label>
      {!admin && <label>推荐说明<textarea maxLength={1000} value={note} onChange={e => { change(); setNote(e.target.value) }} disabled={save.isPending} /></label>}
      <label className="workspace-resolved-choice"><input type="checkbox" required checked={consent} onChange={e => { change(); setConsent(e.target.checked) }} disabled={save.isPending} />我确认这是可公开的 RSS，并同意上述公开范围</label>
      {categories.error && <p role="alert">分类加载失败。<button type="button" onClick={() => void categories.refetch()}>重试</button></p>}
      {save.error && <p role="alert">{workspaceError(save.error)}。表单未变时可重试提交。</p>}
      <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={save.isPending} onClick={onClose}>取消</button><button className="workspace-button" disabled={save.isPending || !consent || !category || !name.trim()}>{save.isPending ? '提交中…' : admin ? '新增并核验' : '提交推荐'}</button></footer>
    </form>
  </WorkspaceModal>
}
