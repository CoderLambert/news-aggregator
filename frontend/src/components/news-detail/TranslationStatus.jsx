/**
 * Translation badge shown next to article category. Reflects backend
 * translation_status field (pending | translating | network_error | failed | success).
 */
export default function TranslationStatus({ news }) {
  const status = news.translation_status
  const retryCount = news.translation_retry_count || 0

  if (!status || status === 'success') return null

  if (status === 'pending') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-amber-50 text-amber-600 border border-amber-200">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
        等待翻译
      </span>
    )
  }

  if (status === 'translating') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-sky-50 text-sky-600 border border-sky-200">
        <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        正在翻译...
      </span>
    )
  }

  if (status === 'network_error') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-orange-50 text-orange-600 border border-orange-200">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        翻译失败（网络错误）{retryCount > 0 && `· 已重试 ${retryCount} 次`}
      </span>
    )
  }

  if (status === 'failed') {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-red-50 text-red-600 border border-red-200"
        title={news.translation_error}
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        翻译失败 {retryCount > 0 && `· 已重试 ${retryCount} 次`}
      </span>
    )
  }

  return null
}
