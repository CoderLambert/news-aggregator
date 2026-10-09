import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Search } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useLanguage } from '@/context/useLanguage'
import { Input } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { SearchMode } from '@/types/news'

interface SearchBarProps {
  value: string
  mode: SearchMode
  onChange: (value: string) => void
  onModeChange: (mode: SearchMode) => void
  historyNavigationKey?: string | null
}

const modes: Record<'zh' | 'en', Array<{ key: SearchMode; label: string }>> = {
  zh: [{ key: 'keyword', label: '关键词' }, { key: 'semantic', label: '语义' }, { key: 'hybrid', label: '混合' }],
  en: [{ key: 'keyword', label: 'Keyword' }, { key: 'semantic', label: 'Semantic' }, { key: 'hybrid', label: 'Hybrid' }],
}

export default function SearchBar({ value, mode, onChange, onModeChange, historyNavigationKey = null }: SearchBarProps) {
  const { lang, t } = useLanguage()
  const [inputState, setInputState] = useState(() => ({ value, display: value, historyNavigationKey }))
  const display = inputState.display
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onChangeRef = useRef(onChange)
  const currentValueRef = useRef(value)
  const lastHistoryNavigationKeyRef = useRef(historyNavigationKey)

  const valueChanged = inputState.value !== value
  const navigationChanged = inputState.historyNavigationKey !== historyNavigationKey
  const returnedFromHistory = historyNavigationKey !== null && navigationChanged
  if (valueChanged || navigationChanged) {
    setInputState({
      value,
      display: valueChanged || returnedFromHistory ? value : inputState.display,
      historyNavigationKey,
    })
  }

  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  useEffect(() => {
    if (currentValueRef.current === value) return
    currentValueRef.current = value
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }, [value])

  useEffect(() => {
    const previousNavigationKey = lastHistoryNavigationKeyRef.current
    lastHistoryNavigationKeyRef.current = historyNavigationKey
    if (historyNavigationKey === null || historyNavigationKey === previousNavigationKey) return
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }, [historyNavigationKey])

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  function handleChange(nextValue: string) {
    setInputState((previous) => ({ ...previous, display: nextValue }))
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      timer.current = null
      onChangeRef.current(nextValue)
    }, 300)
  }

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-gray-400" />
          <Input type="search" value={display} onChange={(event: ChangeEvent<HTMLInputElement>) => handleChange(event.target.value)} placeholder={t.search} aria-label={t.search} className="h-10 rounded-xl pl-10" />
        </div>
        <Link
          to={`/search${display.trim() ? `?q=${encodeURIComponent(display.trim())}&mode=${mode}` : ''}`}
          className="shrink-0 rounded-lg px-2 py-2 text-xs font-medium text-violet-700 hover:bg-violet-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500"
        >
          {lang === 'en' ? 'Advanced' : '高级搜索'}
        </Link>
      </div>
      <ToggleGroup
        type="single"
        value={mode}
        onValueChange={(nextMode: string) => {
          if (nextMode === 'keyword' || nextMode === 'semantic' || nextMode === 'hybrid') onModeChange(nextMode)
        }}
        variant="outline"
        size="sm"
        aria-label={lang === 'en' ? 'Search mode' : '搜索模式'}
        className="rounded-lg"
      >
        {modes[lang].map((option) => (
          <ToggleGroupItem key={option.key} value={option.key} aria-label={option.label} variant="outline" size="sm" className="text-xs font-medium data-[state=on]:bg-blue-500 data-[state=on]:text-white">
            {option.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  )
}
