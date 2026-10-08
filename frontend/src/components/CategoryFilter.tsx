import { useLanguage } from '@/context/useLanguage'
import { Button } from '@/components/ui/button'
import type { FilterOption } from '@/types/news'

interface CategoryFilterProps {
  categories: FilterOption[]
  active?: number[]
  onChange: (ids: number[]) => void
}

export default function CategoryFilter({ categories, active = [], onChange }: CategoryFilterProps) {
  const { lang } = useLanguage()
  const toggle = (id: number) => onChange(active.includes(id) ? active.filter((item) => item !== id) : [...active, id])
  const activeClass = 'bg-blue-600 text-white hover:bg-blue-700'

  return (
    <div className="flex flex-wrap gap-2">
      <Button type="button" size="pill-sm" variant="secondary" aria-pressed={active.length === 0} onClick={() => onChange([])} className={active.length === 0 ? activeClass : ''}>
        {lang === 'en' ? 'All' : '全部'}
      </Button>
      {categories.map((category) => {
        const isActive = active.includes(category.id)
        return <Button key={category.id} type="button" size="pill-sm" variant="secondary" aria-pressed={isActive} onClick={() => toggle(category.id)} className={isActive ? activeClass : ''}>{category.name}</Button>
      })}
    </div>
  )
}
