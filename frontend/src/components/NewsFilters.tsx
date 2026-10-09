import { useId, useState } from 'react'
import { Filter, RotateCcw, X } from 'lucide-react'
import { useLanguage } from '@/context/useLanguage'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import CategoryFilter from '@/components/CategoryFilter'
import SourceFilter from '@/components/SourceFilter'
import type { FilterOption } from '@/types/news'

interface NewsFiltersProps {
  categories: FilterOption[]
  sources: FilterOption[]
  activeCategories: number[]
  activeSources: number[]
  onCategoriesChange: (ids: number[]) => void
  onSourcesChange: (ids: number[]) => void
  onClear: () => void
}

function selectedOptions(options: FilterOption[], active: number[]) {
  const activeIds = new Set(active)
  return options.filter((option) => activeIds.has(option.id))
}

export default function NewsFilters({
  categories,
  sources,
  activeCategories,
  activeSources,
  onCategoriesChange,
  onSourcesChange,
  onClear,
}: NewsFiltersProps) {
  const { lang } = useLanguage()
  const panelId = useId()
  const [expanded, setExpanded] = useState(false)
  const activeCategoryOptions = selectedOptions(categories, activeCategories)
  const activeSourceOptions = selectedOptions(sources, activeSources)
  const activeCount = activeCategories.length + activeSources.length

  return (
    <section aria-label={lang === 'en' ? 'News filters' : '新闻筛选'} className="rounded-2xl border border-neutral-200 bg-neutral-50/70 p-3">
      <div className="flex min-h-9 flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label={activeCount > 0
            ? (lang === 'en' ? `Filters, ${activeCount} selected` : `筛选，已选 ${activeCount} 个条件`)
            : (lang === 'en' ? 'Filters' : '筛选')}
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={() => setExpanded((current) => !current)}
          className="h-11 rounded-full bg-white sm:h-8"
        >
          <Filter aria-hidden="true" />
          {lang === 'en' ? 'Filters' : '筛选'}
          {activeCount > 0 && <span aria-hidden="true" className="flex size-5 items-center justify-center rounded-full bg-neutral-900 text-[11px] text-white">{activeCount}</span>}
        </Button>

        {!expanded && activeCount === 0 && (
          <p className="text-xs text-neutral-500">
            {lang === 'en' ? 'Choose categories or sources' : '按分类或来源缩小结果'}
          </p>
        )}

        {!expanded && activeCategoryOptions.map((category) => (
          <Badge key={`category-${category.id}`} variant="blue" className="min-w-0 max-w-full gap-1 rounded-full py-0.5 pl-2 pr-0.5">
            <span className="max-w-48 truncate">{category.name}</span>
            <button
              type="button"
              aria-label={lang === 'en' ? `Remove category ${category.name}` : `移除分类 ${category.name}`}
              onClick={() => onCategoriesChange(activeCategories.filter((id) => id !== category.id))}
              className="flex size-11 shrink-0 items-center justify-center rounded-full hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:size-7"
            >
              <X aria-hidden="true" className="size-3" />
            </button>
          </Badge>
        ))}

        {!expanded && activeSourceOptions.map((source) => (
          <Badge key={`source-${source.id}`} variant="green" className="min-w-0 max-w-full gap-1 rounded-full py-0.5 pl-2 pr-0.5">
            <span className="max-w-48 truncate">{source.name}</span>
            <button
              type="button"
              aria-label={lang === 'en' ? `Remove source ${source.name}` : `移除来源 ${source.name}`}
              onClick={() => onSourcesChange(activeSources.filter((id) => id !== source.id))}
              className="flex size-11 shrink-0 items-center justify-center rounded-full hover:bg-green-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green-500 sm:size-7"
            >
              <X aria-hidden="true" className="size-3" />
            </button>
          </Badge>
        ))}

        {activeCount > 0 && (
          <Button type="button" variant="ghost" size="sm" onClick={onClear} className="ml-auto h-11 rounded-full text-neutral-600 sm:h-8">
            <RotateCcw aria-hidden="true" />
            {lang === 'en' ? 'Clear' : '清除筛选'}
          </Button>
        )}
      </div>

      {expanded && (
        <div id={panelId} className="mt-3 grid max-h-[min(28rem,60vh)] gap-4 overflow-y-auto border-t border-neutral-200 pt-3 pr-1 lg:grid-cols-2">
          <fieldset className="min-w-0">
            <legend className="mb-2 text-xs font-semibold text-neutral-600">{lang === 'en' ? 'Categories' : '分类'}</legend>
            <CategoryFilter categories={categories} active={activeCategories} onChange={onCategoriesChange} />
          </fieldset>
          <fieldset className="min-w-0">
            <legend className="mb-2 text-xs font-semibold text-neutral-600">{lang === 'en' ? 'Sources' : '来源'}</legend>
            <SourceFilter sources={sources} active={activeSources} onChange={onSourcesChange} />
          </fieldset>
        </div>
      )}
    </section>
  )
}
