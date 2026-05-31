import { ErrorBoundary } from 'react-error-boundary'

function ErrorFallback({ error, resetErrorBoundary }) {
  return (
    <div
      role="alert"
      className="max-w-md mx-auto my-12 p-6 bg-white border border-rose-200 rounded-xl shadow-sm text-center"
    >
      <h2 className="text-lg font-semibold text-rose-600 mb-2">页面出错了</h2>
      <p className="text-sm text-gray-600 mb-4 break-words">{error?.message || '未知错误'}</p>
      <button
        type="button"
        onClick={resetErrorBoundary}
        className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-full hover:bg-indigo-700"
      >
        重新加载
      </button>
    </div>
  )
}

export default function AppErrorBoundary({ children, onReset }) {
  return (
    <ErrorBoundary FallbackComponent={ErrorFallback} onReset={onReset}>
      {children}
    </ErrorBoundary>
  )
}
