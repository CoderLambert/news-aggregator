import { useLanguage } from '@/context/useLanguage'
import type { SourceRegion } from '@/types/news'

export default function RegionFilter({ value, onChange }: { value: SourceRegion | 'all'; onChange: (value: SourceRegion | 'all') => void }) {
  const { lang } = useLanguage()
  const options = [{ value: 'all', name: lang === 'en' ? 'All regions' : '全部' },
    { value: 'domestic', name: lang === 'en' ? 'Domestic' : '国内' },
    { value: 'international', name: lang === 'en' ? 'International' : '国际' }] as const
  return <div role="group" aria-label="频道地区" className="my-3 flex flex-wrap items-center gap-2 text-sm">
    <span className="mr-1 text-muted-foreground">频道地区</span>
    {options.map(option => <button key={option.value} type="button" aria-pressed={value === option.value} onClick={() => onChange(option.value)}
      className={`min-h-11 rounded-lg px-3 focus-visible:outline-2 focus-visible:outline-primary ${value === option.value ? 'bg-primary text-primary-foreground' : 'bg-secondary text-secondary-foreground'}`}>{option.name}</button>)}
  </div>
}
