import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { fetchReviewCategories, rssReviewKey, submitRecommendation, recommendationLabels } from '@/services/rssReviewApi'
import type { ChannelProfile } from '@/services/workspaceApi'
import { useSerialReviewActions } from './useSerialReviewActions'

export default function RecommendChannelsDialog({ viewer, sources, onClose }: {
  viewer: number; sources: ChannelProfile[]; onClose: () => void
}) {
  const client = useQueryClient()
  const [rows, setRows] = useState(() => sources.map(source => ({ id: String(source.id), name: source.name,
    category: '', language: ['zh', 'en'].includes(source.language) ? source.language : 'other' })))
  const [consent, setConsent] = useState(false)
  const [states, setStates] = useState<Record<string, string>>({})
  const batch = useSerialReviewActions()
  const categories = useQuery({ queryKey: [...rssReviewKey(viewer), 'categories'], queryFn: ({ signal }) => fetchReviewCategories(signal), retry: false })
  const valid = rows.length > 0 && rows.length <= 10 && consent && rows.every(row => row.name.trim() && row.category)
  const complete = batch.done.length === rows.length
  function change(id: string, values: Partial<(typeof rows)[number]>) {
    setRows(current => current.map(row => row.id === id ? { ...row, ...values } : row))
  }
  async function submit() {
    if (!valid) return
    await batch.run(rows.map(row => row.id), async (id, key) => {
      const row = rows.find(item => item.id === id)!
      const result = await submitRecommendation(viewer, { source_id: Number(id), name: row.name.trim(),
        category_id: Number(row.category), language: row.language, confirm_public_scope: true }, key)
      // The modal is keyed to the viewer by its parent; private results stay here.
      setStates(current => ({ ...current, [id]: recommendationLabels[result.state] ?? result.state }))
      void client.invalidateQueries({ queryKey: rssReviewKey(viewer) })
    })
  }
  return <WorkspaceModal title="推荐到公共频道" busy={batch.busy} onClose={onClose}>
    <p>每次最多推荐 10 个频道，审核通过后才会公开。公开范围为最近七天内经验证的文章及后续文章；个人分组、阅读和 AI 记录保持私有。</p>
    {rows.map(row => <fieldset key={row.id} disabled={batch.started} className="my-4 grid gap-3 rounded-lg border p-3">
      <legend>{row.name}</legend>
      <label>公开名称<Input aria-label={`公开名称 ${row.id}`} value={row.name} maxLength={255} onChange={e => change(row.id, { name: e.target.value })} /></label>
      <label>分类<NativeSelect aria-label={`分类 ${row.name}`} value={row.category} onChange={e => change(row.id, { category: e.target.value })}>
        <option value="">请选择分类</option>{categories.data?.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}
      </NativeSelect></label>
      <label>语言<NativeSelect aria-label={`语言 ${row.name}`} value={row.language} onChange={e => change(row.id, { language: e.target.value })}>
        <option value="zh">中文</option><option value="en">英文</option><option value="other">其他</option>
      </NativeSelect></label>
      {batch.done.includes(row.id) && <p role="status">{states[row.id] || '已提交'}</p>}
    </fieldset>)}
    <label className="flex items-start gap-2"><Checkbox checked={consent} disabled={batch.started} onChange={e => setConsent(e.target.checked)} />我确认所选 RSS 可公开，并同意上述公开范围</label>
    {categories.isError && <p role="alert">分类读取失败。<Button variant="outline" onClick={() => void categories.refetch()}>重试</Button></p>}
    {batch.started && <p role="status">已完成 {batch.done.length} / {rows.length} 个推荐</p>}
    {batch.error && <p role="alert">{batch.error}。已完成的推荐会保留；继续时只处理未完成项。需要修改资料时请关闭后重新选择。</p>}
    <footer className="workspace-modal-actions">
      <Button variant="outline" disabled={batch.busy} onClick={onClose}>关闭</Button>
      {complete ? <Button asChild><Link to="/channels/additions?tab=recommendations">查看我的推荐</Link></Button>
        : <Button disabled={!valid || batch.busy || categories.isError} onClick={() => void submit()}>{batch.busy ? '提交中…' : batch.started ? '继续提交未完成项' : '提交推荐'}</Button>}
    </footer>
  </WorkspaceModal>
}
