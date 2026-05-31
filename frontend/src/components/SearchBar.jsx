import { useState, useRef, useEffect } from 'react'
import { Search } from 'lucide-react'
import { useLanguage } from '../context/useLanguage'
import { Input } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

const MODES = {
  zh: [
    { key: 'keyword', label: '关键词' },
    { key: 'semantic', label: '语义' },
    { key: 'hybrid', label: '混合' },
  ],
  en: [
    { key: 'keyword', label: 'Keyword' },
    { key: 'semantic', label: 'Semantic' },
    { key: 'hybrid', label: 'Hybrid' },
  ],
}

export default function SearchBar({ value, onChange, mode, onModeChange }) {
  const { lang, t } = useLanguage()
  // Track the last prop we synced from. When parent pushes a new `value`
  // (e.g. on filter clear or saved-filter restore), we adopt it without an
  // effect. This is React's official "adjusting state while rendering"
  // pattern — see https://react.dev/learn/you-might-not-need-an-effect
  // #adjusting-some-state-when-a-prop-changes
  const [display, setDisplay] = useState(value)
  const [syncedValue, setSyncedValue] = useState(value)
  const timer = useRef(null)

  if (value !== syncedValue) {
    setSyncedValue(value)
    setDisplay(value)
  }

  // Cancel any pending debounce on unmount so we don't fire onChange after
  // the component is gone.
  useEffect(() => () => clearTimeout(timer.current), [])

  const handleChange = (e) => {
    const v = e.target.value
    setDisplay(v)                                 // immediate UI feedback
    clearTimeout(timer.current)
    timer.current = setTimeout(() => onChange(v), 300)
  }

  const modes = MODES[lang] || MODES.zh

  return (
    <div className="flex items-center gap-2">
      <div className="relative flex-1">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-gray-400 pointer-events-none" />
        <Input
          type="text"
          value={display}
          onChange={handleChange}
          placeholder={t.search}
          className="pl-10 h-10 rounded-lg"
        />
      </div>
      {/* Single-select toggle for search mode (keyword/semantic/hybrid). */}
      <ToggleGroup
        type="single"
        value={mode}
        onValueChange={(v) => v && onModeChange?.(v)}
        variant="outline"
        className="rounded-lg"
      >
        {modes.map(m => (
          <ToggleGroupItem
            key={m.key}
            value={m.key}
            aria-label={m.label}
            className="text-xs font-medium data-[state=on]:bg-blue-500 data-[state=on]:text-white"
          >
            {m.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  )
}
