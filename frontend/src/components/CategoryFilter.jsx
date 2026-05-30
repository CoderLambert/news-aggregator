import { useLanguage } from '../context/LanguageContext'

export default function CategoryFilter({ categories, active = [], onChange }) {
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
            ? 'bg-blue-600 text-white'
            : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
      >
        {lang === 'en' ? 'All' : '全部'}
      </button>
      {categories.map(cat => (
        <button
          key={cat.id}
          onClick={() => toggle(cat.id)}
          className={`px-3 py-1 rounded-full text-sm font-medium transition-colors
            ${active.includes(cat.id)
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
        >
          {cat.name}
        </button>
      ))}
    </div>
  )
}
