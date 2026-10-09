import { lazy, Suspense, useState } from 'react'
import { ErrorBoundary } from 'react-error-boundary'
import LazyModalState from '@/components/LazyModalState'
import { loadNewsChatAssistant, reloadNewsChatPage } from './newsChatAssistantLoader'

interface LazyNewsChatAssistantProps {
  newsId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function LazyNewsChatAssistant({ newsId, open, onOpenChange }: LazyNewsChatAssistantProps) {
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [NewsChatAssistant, setNewsChatAssistant] = useState(() => lazy(loadNewsChatAssistant))

  function handleLoadRetry(resetErrorBoundary: () => void) {
    setNewsChatAssistant(() => lazy(loadNewsChatAssistant))
    setLoadAttempt((attempt) => attempt + 1)
    resetErrorBoundary()
  }

  if (!open) return null

  return (
    <ErrorBoundary
      key={loadAttempt}
      fallbackRender={({ resetErrorBoundary }) => (
        <LazyModalState
          label="AI 助手小闻"
          message="小闻加载失败。可先重试；若仍失败，请刷新页面获取最新资源。"
          onClose={() => onOpenChange(false)}
          onReload={reloadNewsChatPage}
          onRetry={() => handleLoadRetry(resetErrorBoundary)}
          variant="chat"
        />
      )}
    >
      <Suspense fallback={<LazyModalState label="AI 助手小闻" message="正在打开小闻…" onClose={() => onOpenChange(false)} variant="chat" />}>
        <NewsChatAssistant newsId={newsId} open onOpenChange={onOpenChange} />
      </Suspense>
    </ErrorBoundary>
  )
}
