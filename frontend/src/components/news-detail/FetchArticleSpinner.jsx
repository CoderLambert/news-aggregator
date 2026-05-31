/**
 * FetchArticleSpinner — shown while the Jina Reader extraction is in flight.
 */
export default function FetchArticleSpinner() {
  return (
    <div className="mb-6 p-8 bg-gray-50 rounded-xl border border-gray-200 text-center">
      <svg className="w-8 h-8 mx-auto text-indigo-500 animate-spin mb-3" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <p className="text-sm text-gray-500">正在获取原文内容...</p>
    </div>
  )
}
