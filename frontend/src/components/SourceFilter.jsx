import { useLanguage } from '../context/useLanguage'

export default function SourceFilter({ sources, active = [], onChange }) {
  const { lang } = useLanguage()

  const toggle = (id) => {
    if (active.includes(id)) {
      onChange(active.filter(a => a !== id))
    } else {
      onChange([...active, id])
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      <button
        onClick={() => onChange([])}
        className={`px-3 py-1 rounded-full text-sm font-medium transition-colors
          ${active.length === 0
            ? 'bg-emerald-600 text-white'
            : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
      >
        {lang === 'en' ? 'All Sources' : '全部来源'}
      </button>
      {sources.map(src => (
        <button
          key={src.id}
          onClick={() => toggle(src.id)}
          className={`px-3 py-1 rounded-full text-sm font-medium transition-colors
            ${active.includes(src.id)
              ? 'bg-emerald-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
        >
          {src.name}
        </button>
      ))}
    </div>
  )
}
