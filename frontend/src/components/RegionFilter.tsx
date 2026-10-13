import { useLanguage } from '@/context/useLanguage'
import type { SourceRegion } from '@/types/news'

export default function RegionFilter({ value, onChange, compact = false }: {
  value: SourceRegion | 'all'
  onChange: (value: SourceRegion | 'all') => void
  compact?: boolean
}) {
  const { lang } = useLanguage()
  const options = [{ value: 'all', name: lang === 'en' ? 'All regions' : '全部' },
    { value: 'domestic', name: lang === 'en' ? 'Domestic' : '国内' },
    { value: 'international', name: lang === 'en' ? 'International' : '国际' }] as const
  return <div role="group" aria-label="频道地区" className={compact
    ? 'flex flex-wrap items-center gap-1.5 text-sm'
    : 'my-3 flex flex-wrap items-center gap-2 text-sm'}>
    <span className="mr-1 shrink-0 text-xs text-muted-foreground">{compact ? '地区' : '频道地区'}</span>
    {options.map(option => <button key={option.value} type="button" aria-pressed={value === option.value} onClick={() => onChange(option.value)}
      className={value === option.value
        ? 'min-h-10 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground focus-visible:outline-2 focus-visible:outline-primary'
        : 'min-h-10 rounded-lg px-3 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary'}>
      {option.name}
    </button>)}
  </div>
}
