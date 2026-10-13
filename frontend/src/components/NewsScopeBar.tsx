import { Link, useLocation } from 'react-router-dom'
import type { ChannelGroup, NewsScope } from '@/types/channels'
import type { SourceRegion } from '@/types/news'
import RegionFilter from '@/components/RegionFilter'

export default function NewsScopeBar({ scope, groupId, groups, personal, accounts, resultCount, onChange, region, onRegionChange }: {
  scope: NewsScope
  groupId?: number
  groups: ChannelGroup[]
  personal: boolean
  accounts: boolean
  resultCount?: number
  onChange: (value: string) => void
  region: SourceRegion | 'all'
  onRegionChange: (value: SourceRegion | 'all') => void
}) {
  const location = useLocation()
  const value = scope === 'group' ? 'group:' + groupId : scope
  const options = [{ value: 'all', name: '全部资讯' }, ...(personal ? [
    { value: 'subscribed', name: '我的订阅' }, { value: 'ungrouped', name: '未加入分组' },
    ...groups.map(g => ({ value: 'group:' + g.id, name: g.name })),
  ] : [])]

  return <section aria-label="资讯范围" className="rounded-2xl border border-border bg-card px-3 py-2.5 sm:px-4">
    <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
      <div className="min-w-0 flex-1">
        <label className="flex min-h-11 items-center gap-2 text-sm md:hidden">
          <span className="shrink-0 text-muted-foreground">阅读范围</span>
          <select aria-label="查看范围" className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2.5" value={value} onChange={e => onChange(e.target.value)}>
            {options.map(o => <option key={o.value} value={o.value}>{o.name}</option>)}
          </select>
        </label>
        <div className="hidden min-w-0 items-center gap-1.5 md:flex">
          <span className="mr-1 shrink-0 text-xs text-muted-foreground">阅读范围</span>
          <div className="flex min-w-0 flex-wrap gap-1.5">
            {options.map(o => <button type="button" key={o.value} aria-pressed={value === o.value}
              title={o.value === 'ungrouped' ? '已订阅、但还没有加入任何分组的频道' : undefined}
              onClick={() => onChange(o.value)}
              className={value === o.value
                ? 'min-h-10 max-w-44 truncate rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground focus-visible:outline-2 focus-visible:outline-primary'
                : 'min-h-10 max-w-44 truncate rounded-lg px-3 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary'}>
              {o.name}
            </button>)}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-border/70 pt-2 lg:shrink-0 lg:border-l lg:border-t-0 lg:py-0 lg:pl-3">
        {resultCount !== undefined && <span className="shrink-0 text-xs text-muted-foreground"><strong className="font-mono font-semibold text-foreground">{resultCount}</strong> 篇内容</span>}
        <RegionFilter compact value={region} onChange={onRegionChange} />
        <Link to="/channels" state={{ newsReturnTo: location.pathname + location.search }}
          className="inline-flex min-h-10 shrink-0 items-center rounded-lg px-2 text-sm font-medium text-primary hover:bg-secondary focus-visible:outline-2 focus-visible:outline-primary">
          {accounts ? '管理频道' : '频道目录'} <span aria-hidden="true" className="ml-1">→</span>
        </Link>
      </div>
    </div>
    {personal && scope === 'ungrouped' && <p role="status" className="mt-2 border-t border-border/70 pt-2 text-xs text-muted-foreground">
      这里只显示已订阅、但还没加入任何分组的频道资讯。
      <Link to="/channels" state={{ newsReturnTo: location.pathname + location.search }} className="ml-2 text-primary underline">整理到分组</Link>
    </p>}
  </section>
}
