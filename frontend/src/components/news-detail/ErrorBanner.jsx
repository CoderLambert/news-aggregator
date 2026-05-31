/**
 * ErrorBanner — generic inline error with a retry affordance.
 *
 * Used for both article-fetch and translation errors on the detail page.
 */
export default function ErrorBanner({ message, onRetry }) {
  return (
    <div className="mb-6 p-4 bg-red-50 rounded-xl border border-red-200" role="alert">
      <div className="flex items-center gap-2 text-red-600 text-sm">
        <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>{message}</span>
        <button
          type="button"
          onClick={onRetry}
          className="ml-auto text-xs underline hover:no-underline"
        >
          重试
        </button>
      </div>
    </div>
  )
}
