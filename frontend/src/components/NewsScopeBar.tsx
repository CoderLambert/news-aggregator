import { Link, useLocation } from 'react-router-dom'
import type { ChannelGroup, NewsScope } from '@/types/channels'

export default function NewsScopeBar({ scope, groupId, groups, personal, accounts, onChange }: {
  scope: NewsScope; groupId?: number; groups: ChannelGroup[]; personal: boolean; accounts: boolean; onChange: (value: string) => void
}) {
  const location = useLocation()
  const value = scope === 'group' ? `group:${groupId}` : scope
  const options = [{ value: 'all', name: '全部资讯' }, ...(personal ? [
    { value: 'subscribed', name: '我的订阅' }, { value: 'ungrouped', name: '未加入分组' },
    ...groups.map(g => ({ value: `group:${g.id}`, name: g.name })),
  ] : [])]
  return <section aria-label="资讯范围" className="mb-4 rounded-xl border border-border bg-card p-3">
    <div className="flex items-center gap-3">
      <label className="flex min-w-0 flex-1 items-center gap-2 md:hidden">查看范围
        <select aria-label="查看范围" className="min-w-0 flex-1 rounded border border-border bg-background p-2" value={value} onChange={e => onChange(e.target.value)}>
          {options.map(o => <option key={o.value} value={o.value}>{o.name}</option>)}
        </select>
      </label>
      <div className="hidden min-w-0 flex-1 flex-wrap gap-2 md:flex">
        {options.map(o => <button type="button" key={o.value} aria-pressed={value === o.value} title={o.value === 'ungrouped' ? '已订阅、但还没有加入任何分组的频道' : undefined} onClick={() => onChange(o.value)}
          className={`min-h-10 max-w-full truncate rounded-lg px-3 text-sm focus-visible:outline-2 focus-visible:outline-primary ${value === o.value ? 'bg-primary text-primary-foreground' : 'bg-secondary text-secondary-foreground'}`}>{o.name}</button>)}
      </div>
      <Link to="/channels" state={{ newsReturnTo: location.pathname + location.search }} className="shrink-0 rounded px-2 py-3 text-sm text-primary underline">{accounts ? '管理频道' : '频道目录'}</Link>
    </div>
    {personal && scope === 'ungrouped' && <p role="status" className="mt-2 text-sm text-muted-foreground">
      这里只显示已订阅、但还没加入任何分组的频道资讯。
      <Link to="/channels" state={{ newsReturnTo: location.pathname + location.search }} className="ml-2 text-primary underline">整理到分组</Link>
    </p>}
  </section>
}
