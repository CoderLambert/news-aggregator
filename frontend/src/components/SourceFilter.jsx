import { useLanguage } from '../context/useLanguage'
import { Button } from '@/components/ui/button'

/**
 * Source chip filter — same UX as CategoryFilter but with emerald accent.
 *
 * We don't share a helper between the two on purpose: they pass through to
 * the same ChipFilter primitive defined inside CategoryFilter.jsx and
 * sharing it across files would require a new public module without much
 * benefit (each filter is ~25 lines once shadcn'd).
 */
function ChipFilter({ items, active, onChange, allLabel }) {
  const toggle = (id) =>
    active.includes(id)
      ? onChange(active.filter(a => a !== id))
      : onChange([...active, id])

  const activeClass = 'bg-emerald-600 text-white hover:bg-emerald-700'

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

export default function SourceFilter({ sources, active = [], onChange }) {
  const { lang } = useLanguage()
  return (
    <ChipFilter
      items={sources}
      active={active}
      onChange={onChange}
      allLabel={lang === 'en' ? 'All Sources' : '全部来源'}
    />
  )
}
