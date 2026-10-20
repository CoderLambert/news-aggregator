import { useState } from 'react'
import { safeExternalUrl, type ChannelProfile, type Topic } from '@/services/workspaceApi'

export function ChannelMark({ source }: { source: Pick<ChannelProfile, 'name' | 'logo' | 'topics'> }) {
  const [failed, setFailed] = useState(false)
  const logo = safeExternalUrl(source.logo)
  return <span className="workspace-channel-mark" data-topic={source.topics[0]} aria-hidden="true">
    {logo && !failed ? <img src={logo} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} /> : source.name.slice(0, 2)}
  </span>
}
export function TopicTags({ keys, topics }: { keys: string[]; topics: Topic[] }) {
  return <span className="workspace-topic-tags">{keys.length ? keys.map(key => <span key={key} data-topic={key}>{topics.find(topic => topic.key === key)?.name ?? key}</span>) : <span data-topic="unknown">待分类</span>}</span>
}
export function Availability({ source }: { source: ChannelProfile }) {
  if (source.subscription_status === 'active') return null
  const reasons: Record<string, string> = { source_policy_not_permitted: '来源授权已变更，暂不开放订阅', feed_verification_pending: 'RSS 待验证，暂不开放订阅', feed_error: 'RSS 连接失败，暂不开放订阅', feed_outcome_unknown: '连接结果待核对，暂不开放订阅', connecting: '正在连接来源', error: '连接失败，请查看订阅状态', unknown: '连接结果待核对', paused: '采集已暂停，可阅读历史内容' }
  return <span className="workspace-caption">{reasons[source.subscription_reason] ?? '来源已停用，可阅读历史内容'}</span>
}
