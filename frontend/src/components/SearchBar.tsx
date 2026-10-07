import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Search } from 'lucide-react'
import { useLanguage } from '@/context/useLanguage'
import { Input } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { SearchMode } from '@/types/news'

interface SearchBarProps {
  value: string
  mode: SearchMode
  onChange: (value: string) => void
  onModeChange: (mode: SearchMode) => void
}

const modes: Record<'zh' | 'en', Array<{ key: SearchMode; label: string }>> = {
  zh: [{ key: 'keyword', label: '关键词' }, { key: 'semantic', label: '语义' }, { key: 'hybrid', label: '混合' }],
  en: [{ key: 'keyword', label: 'Keyword' }, { key: 'semantic', label: 'Semantic' }, { key: 'hybrid', label: 'Hybrid' }],
}

export default function SearchBar({ value, mode, onChange, onModeChange }: SearchBarProps) {
  const { lang, t } = useLanguage()
  const [display, setDisplay] = useState(value)
  const [syncedValue, setSyncedValue] = useState(value)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onChangeRef = useRef(onChange)
  const currentValueRef = useRef(value)

  if (value !== syncedValue) {
    setSyncedValue(value)
    setDisplay(value)
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

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  function handleChange(nextValue: string) {
    setDisplay(nextValue)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      timer.current = null
      onChangeRef.current(nextValue)
    }, 300)
  }

  return (
    <div className="flex items-center gap-2">
      <div className="relative min-w-0 flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-gray-400" />
        <Input type="search" value={display} onChange={(event: ChangeEvent<HTMLInputElement>) => handleChange(event.target.value)} placeholder={t.search} aria-label={t.search} className="h-10 rounded-lg pl-10" />
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
