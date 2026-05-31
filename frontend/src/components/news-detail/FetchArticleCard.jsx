/**
 * FetchArticleCard — "load full article via Jina Reader" CTA.
 *
 * Pure presentational; clicking the button invokes onFetch.
 */
export default function FetchArticleCard({ onFetch }) {
  return (
    <div className="mb-6 p-4 bg-gradient-to-r from-indigo-50 to-blue-50 rounded-xl border border-indigo-100">
      <div className="flex items-center gap-3 mb-3">
        <svg className="w-5 h-5 text-indigo-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
        </svg>
        <div>
          <p className="text-sm font-medium text-gray-900">获取完整原文</p>
          <p className="text-xs text-gray-500">通过 Jina Reader 自动提取正文内容</p>
        </div>
      </div>
      <button
        onClick={onFetch}
        aria-label="加载原文"
        className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-full hover:bg-indigo-700 active:scale-95 transition-all duration-200 shadow-sm hover:shadow"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m0 0v8" />
        </svg>
        加载原文
      </button>
    </div>
  )
}
