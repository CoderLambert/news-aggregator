import { useLanguage } from '@/context/useLanguage'
import { Button } from '@/components/ui/button'
import type { FilterOption } from '@/types/news'

interface SourceFilterProps {
  sources: FilterOption[]
  active?: number[]
  onChange: (ids: number[]) => void
}

export default function SourceFilter({ sources, active = [], onChange }: SourceFilterProps) {
  const { lang } = useLanguage()
  const toggle = (id: number) => onChange(active.includes(id) ? active.filter((item) => item !== id) : [...active, id])
  const activeClass = 'bg-emerald-600 text-white hover:bg-emerald-700'

  return (
    <div className="flex flex-wrap gap-2">
      <Button type="button" size="pill-sm" variant="secondary" aria-pressed={active.length === 0} onClick={() => onChange([])} className={active.length === 0 ? activeClass : ''}>
        {lang === 'en' ? 'All Sources' : '全部来源'}
      </Button>
      {sources.map((source) => {
        const isActive = active.includes(source.id)
        return <Button key={source.id} type="button" size="pill-sm" variant="secondary" aria-pressed={isActive} onClick={() => toggle(source.id)} className={isActive ? activeClass : ''}>{source.name}</Button>
      })}
    </div>
  )
}
