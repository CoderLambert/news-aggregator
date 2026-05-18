export default function CategoryFilter({ categories, active, onChange }) {
  return (
    <div className="flex flex-wrap gap-2">
      <button
        onClick={() => onChange(null)}
        className={`px-3 py-1 rounded-full text-sm font-medium transition-colors
          ${active === null
            ? 'bg-blue-600 text-white'
            : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
      >
        全部
      </button>
      {categories.map(cat => (
        <button
          key={cat.id}
          onClick={() => onChange(cat.id)}
          className={`px-3 py-1 rounded-full text-sm font-medium transition-colors
            ${active === cat.id
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
        >
          {cat.name}
        </button>
      ))}
    </div>
  )
}
