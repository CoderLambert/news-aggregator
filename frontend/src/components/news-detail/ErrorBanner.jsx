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
    <Alert variant="destructive" className="mb-6 border-destructive/30 bg-destructive/10">
      <AlertCircle />
      <AlertDescription className="flex items-center justify-between text-destructive">
        <span>{message}</span>
        <Button
          type="button"
          variant="link"
          size="sm"
          onClick={() => onRetry()}
          className="h-auto p-0 text-xs text-destructive underline hover:no-underline"
        >
          重试
        </Button>
      </AlertDescription>
    </Alert>
  )
}
