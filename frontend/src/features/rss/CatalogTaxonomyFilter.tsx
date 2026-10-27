import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/native-select'
import type { CatalogFilters, CatalogSection } from '@/features/rss/catalogTaxonomy'

export default function CatalogTaxonomyFilter({ sections, value, onChange, disabled = false }: {
  sections: CatalogSection[]; value: CatalogFilters; onChange: (value: CatalogFilters) => void; disabled?: boolean
}) {
  if (!sections.length) return null
  const children = sections.find(section => section.key === value.section)?.groups ?? []
  return <fieldset className="space-y-3 rounded-lg border border-border p-3" disabled={disabled}>
    <legend className="px-1 text-sm font-medium">默认 RSS 栏目</legend>
    <div role="group" aria-label="默认 RSS 一级栏目" className="flex flex-wrap gap-2">
      <Button type="button" variant={value.section ? 'outline' : 'secondary'} aria-pressed={!value.section}
        disabled={disabled} onClick={() => onChange({ ...value, section: '', group: '' })}>全部栏目</Button>
      {sections.map(section => <Button key={section.key} type="button" disabled={disabled}
        variant={value.section === section.key ? 'secondary' : 'outline'} aria-pressed={value.section === section.key}
        onClick={() => onChange({ ...value, section: section.key, group: '' })}>{section.label} {section.count}</Button>)}
    </div>
    <div className="grid gap-3 sm:grid-cols-3">
      <label className="text-sm">二级分组<NativeSelect aria-label="默认 RSS 二级分组" value={value.group}
        disabled={disabled || !value.section} onChange={event => onChange({ ...value, group: event.target.value })}>
        <option value="">{value.section ? '全部分组' : '先选择一级栏目'}</option>
        {children.map(group => <option key={group.key} value={group.key}>{group.label} ({group.count})</option>)}
      </NativeSelect></label>
      <label className="text-sm">语言<NativeSelect aria-label="订阅源语言" value={value.language} disabled={disabled}
        onChange={event => onChange({ ...value, language: event.target.value })}>
        <option value="">全部语言</option><option value="zh">中文</option><option value="en">英文</option>
      </NativeSelect></label>
      <label className="text-sm">地区<NativeSelect aria-label="订阅源地区" value={value.region} disabled={disabled}
        onChange={event => onChange({ ...value, region: event.target.value })}>
        <option value="">全部地区</option><option value="domestic">国内</option><option value="international">国际</option>
      </NativeSelect></label>
    </div>
    <p className="text-xs text-muted-foreground">栏目数量是目录中去重后的 Feed 数，不是新增订阅数或独立媒体数。订阅仍需确认；来源未声明地区时不推测归属。</p>
  </fieldset>
}
