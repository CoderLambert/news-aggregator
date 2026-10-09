import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { ErrorBoundary } from 'react-error-boundary'
import LazyModalState from '@/components/LazyModalState'
import ResearchBubbleButton from './ResearchBubbleButton'
import { loadResearchPanel, prefetchResearchPanel } from './researchPanelLoader'

const InitialLazyResearchPanel = lazy(loadResearchPanel)

export default function ResearchLauncher() {
  const [open, setOpen] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [LazyResearchPanel, setLazyResearchPanel] = useState(() => InitialLazyResearchPanel)
  const launcherRef = useRef<HTMLButtonElement | null>(null)
  const restoreFocusRef = useRef(false)

  useEffect(() => {
    if (open || !restoreFocusRef.current) return
    restoreFocusRef.current = false
    launcherRef.current?.focus()
  }, [open])

  function handleClose() {
    restoreFocusRef.current = true
    setOpen(false)
  }

  function handleLoadRetry(resetErrorBoundary: () => void) {
    const NextResearchPanel = lazy(loadResearchPanel)
    setLazyResearchPanel(() => NextResearchPanel)
    setLoadAttempt((attempt) => attempt + 1)
    resetErrorBoundary()
  }

  return (
    <>
      {!open && (
        <ResearchBubbleButton
          buttonRef={launcherRef}
          onOpen={() => setOpen(true)}
          onIntent={prefetchResearchPanel}
        />
      )}
      {open && (
        <ErrorBoundary
          key={loadAttempt}
          onReset={() => setLoadAttempt((attempt) => attempt + 1)}
          fallbackRender={({ resetErrorBoundary }) => (
            <LazyModalState
              label="新闻研究助手"
              message="研究助手加载失败，请检查网络后重试。"
              onClose={handleClose}
              onRetry={() => handleLoadRetry(resetErrorBoundary)}
              variant="research"
            />
          )}
        >
          <Suspense fallback={<LazyModalState label="新闻研究助手" message="正在打开研究助手…" onClose={handleClose} variant="research" />}>
            <LazyResearchPanel onClose={handleClose} />
          </Suspense>
        </ErrorBoundary>
      )}
    </>
  )
}
