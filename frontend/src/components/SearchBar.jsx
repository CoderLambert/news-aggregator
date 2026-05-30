import { useState, useEffect, useRef } from 'react'
import { useLanguage } from '../context/LanguageContext'

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
  const [input, setInput] = useState(value)
  const timer = useRef(null)

  useEffect(() => {
    setInput(value)
  }, [value])

  const handleChange = (e) => {
    setInput(e.target.value)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => onChange(e.target.value), 300)
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
          value={input}
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
