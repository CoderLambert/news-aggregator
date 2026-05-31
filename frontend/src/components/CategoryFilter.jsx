import { useLanguage } from '../context/useLanguage'
import { Button } from '@/components/ui/button'

/**
 * Multi-select chip filter. Used for both categories and sources via the
 * `accent` prop ('blue' for categories, 'emerald' for sources).
 *
 * The "All" chip is a special-case that clears the selection — when
 * nothing is selected, it shows as active. Individual chips toggle.
 */
function ChipFilter({ items, active, onChange, allLabel, accent }) {
  const toggle = (id) =>
    active.includes(id)
      ? onChange(active.filter(a => a !== id))
      : onChange([...active, id])

  const activeClass = accent === 'emerald'
    ? 'bg-emerald-600 text-white hover:bg-emerald-700'
    : 'bg-blue-600 text-white hover:bg-blue-700'

  return (
    <div className="flex flex-wrap gap-2">
      <Button
        type="button"
        size="pill-sm"
        variant="secondary"
        onClick={() => onChange([])}
        className={active.length === 0 ? activeClass : ''}
      >
        {allLabel}
      </Button>
      {items.map(item => {
        const isActive = active.includes(item.id)
        return (
          <Button
            key={item.id}
            type="button"
            size="pill-sm"
            variant="secondary"
            onClick={() => toggle(item.id)}
            className={isActive ? activeClass : ''}
          >
            {item.name}
          </Button>
        )
      })}
    </div>
  )
}

export default function CategoryFilter({ categories, active = [], onChange }) {
  const { lang } = useLanguage()
  return (
    <ChipFilter
      items={categories}
      active={active}
      onChange={onChange}
      allLabel={lang === 'en' ? 'All' : '全部'}
      accent="blue"
    />
  )
}
