export default function SourceFilter({ sources, active, onChange }) {
  return (
    <div className="flex flex-wrap gap-2">
      <button
        onClick={() => onChange(null)}
        className={`px-3 py-1 rounded-full text-sm font-medium transition-colors
          ${active === null
            ? 'bg-emerald-600 text-white'
            : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
      >
        全部来源
      </button>
      {sources.map(src => (
        <button
          key={src.id}
          onClick={() => onChange(src.id)}
          className={`px-3 py-1 rounded-full text-sm font-medium transition-colors
            ${active === src.id
              ? 'bg-emerald-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
        >
          {src.name}
        </button>
      ))}
    </div>
  )
}
