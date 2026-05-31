import { AlertCircle } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

/**
 * ErrorBanner — generic inline error with a retry affordance.
 *
 * Used for both article-fetch and translation errors on the detail page.
 * Wraps shadcn <Alert variant="destructive"> with a trailing retry link.
 */
export default function ErrorBanner({ message, onRetry }) {
  return (
    <Alert variant="destructive" className="mb-6 border-red-200 bg-red-50">
      <AlertCircle />
      <AlertDescription className="flex items-center justify-between text-red-600">
        <span>{message}</span>
        <Button
          type="button"
          variant="link"
          size="sm"
          onClick={onRetry}
          className="h-auto p-0 text-xs text-red-600 underline hover:no-underline"
        >
          重试
        </Button>
      </AlertDescription>
    </Alert>
  )
}
