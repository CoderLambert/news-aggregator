import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { changeChannelSubscriptions } from '@/services/api'
import { useChannelMutation } from '@/services/channelQueries'
import { workspaceRequest, workspaceKeys, workspaceError, type ChannelProfile, type Topic } from '@/services/workspaceApi'
import WorkspaceModal from './WorkspaceModal'
import { Availability, ChannelMark, TopicTags } from './ChannelIdentity'

export default function AddChannelDialog({ topics, onClose, onDone }: { topics: Topic[]; onClose: () => void; onDone: () => void }) {
  const [url, setUrl] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const client = useQueryClient()
  const subscribe = useChannelMutation()
  const resolve = useMutation({ mutationFn: (value: string) => workspaceRequest<{ matches: ChannelProfile[]; supported: boolean; message: string; url: string }>('/smart-channels/resolve/', { method: 'POST', body: { url: value } }),
    onSuccess: data => setSelectedId(data.matches.length === 1 ? data.matches[0].id : null) })
  const intake = useMutation({ mutationFn: (value: string) => workspaceRequest('/me/smart-channels/intake/', { method: 'POST', body: { url: value } }), onSuccess: () => { void client.invalidateQueries({ queryKey: workspaceKeys.all }) } })
  const busy = resolve.isPending || subscribe.isPending || intake.isPending
  const selected = resolve.data?.matches.find(source => source.id === selectedId)
  return <WorkspaceModal title="订阅频道" busy={busy} onClose={onClose}>
    <p className="workspace-muted">输入已支持频道的网站或 RSS 地址。全站采集配置不随个人订阅改变。</p>
    <form className="workspace-inline-form" onSubmit={event => { event.preventDefault(); intake.reset(); resolve.mutate(url.trim()) }}>
      <label className="workspace-grow">网站或 RSS 地址<input type="url" required value={url} placeholder="https://react.dev/rss.xml" disabled={busy}
        onChange={event => { setUrl(event.target.value); resolve.reset(); intake.reset(); setSelectedId(null) }} /></label>
      <button type="submit" className="workspace-button" disabled={busy || !url.trim()}>{resolve.isPending ? '匹配中…' : '匹配频道'}</button>
    </form>
    {resolve.isError && <p role="alert" className="workspace-error">{workspaceError(resolve.error)}</p>}
    {resolve.data && <section className="workspace-resolved"><p>{resolve.data.message}</p>
      {resolve.data.matches.map(source => <label key={source.id} className="workspace-resolved-choice">
        <input type="radio" name="resolved-channel" value={source.id} checked={selectedId === source.id} disabled={busy} onChange={() => setSelectedId(source.id)} />
        <ChannelMark source={source} /><span><strong>{source.name}</strong><small>{source.description || '暂无频道简介'}</small><TopicTags keys={source.topics} topics={topics} /><Availability source={source} /></span>
      </label>)}
      {selected && <div className="workspace-soft-panel"><strong>分组建议</strong><TopicTags keys={selected.topics} topics={topics} />
        <p className="workspace-caption">按已保存的整理模式推荐或加入已有分组。信息不足时保留待确认，不覆盖人工调整。</p></div>}
      {!resolve.data.supported && <button type="button" className="workspace-button secondary" disabled={busy || intake.isSuccess} onClick={() => intake.mutate(resolve.data!.url)}>{intake.isSuccess ? '已提交，等待接入审核' : '提交频道接入申请'}</button>}
    </section>}
    {intake.isError && <p role="alert" className="workspace-error">{workspaceError(intake.error)}</p>}
    {subscribe.isError && <p role="alert" className="workspace-error">订阅未成功，请重试。</p>}
    <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={busy} onClick={onClose}>取消</button>
      <button type="button" className="workspace-button" disabled={busy || !selected || selected.subscription_status !== 'active'} onClick={() => {
        if (!selected) return
        subscribe.mutate(() => changeChannelSubscriptions({ action: 'subscribe', source_ids: [selected.id] }), {
          onSuccess: () => { void client.invalidateQueries({ queryKey: workspaceKeys.all }); onDone() },
        })
      }}>{subscribe.isPending ? '订阅中…' : '确认订阅'}</button></footer>
  </WorkspaceModal>
}
