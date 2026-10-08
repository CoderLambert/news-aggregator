import { ErrorBoundary } from 'react-error-boundary'
import type { FallbackProps } from 'react-error-boundary'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'

function ErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  return (
    <section role="alert" className="mx-auto my-12 max-w-md rounded-xl border border-destructive/30 bg-card p-6 text-center shadow-sm">
      <h2 className="mb-2 text-lg font-semibold text-destructive">页面出错了</h2>
      <p className="mb-4 break-words text-sm text-muted-foreground">{error instanceof Error && error.message ? error.message : '未知错误'}</p>
      <Button type="button" onClick={resetErrorBoundary}>重新加载</Button>
    </section>
  )
}

interface AppErrorBoundaryProps {
  children: ReactNode
  onReset?: () => void
}

export default function AppErrorBoundary({ children, onReset }: AppErrorBoundaryProps) {
  return <ErrorBoundary FallbackComponent={ErrorFallback} onReset={onReset}>{children}</ErrorBoundary>
}
