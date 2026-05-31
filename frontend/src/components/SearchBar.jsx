import { useState, useRef, useEffect } from 'react'
import { useLanguage } from '../context/useLanguage'

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
        <svg
          className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          type="text"
          value={display}
          onChange={handleChange}
          placeholder={t.search}
          className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg text-sm
            focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>
      <div className="flex border border-gray-300 rounded-lg overflow-hidden">
        {modes.map(m => (
          <button
            key={m.key}
            onClick={() => onModeChange?.(m.key)}
            className={`px-3 py-2 text-xs font-medium transition-colors
              ${mode === m.key
                ? 'bg-blue-500 text-white'
                : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
          >
            {m.label}
          </button>
        ))}
      </div>
    </div>
  )
}
