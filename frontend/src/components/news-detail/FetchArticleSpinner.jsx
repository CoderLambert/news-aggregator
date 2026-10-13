import { Loader2, XCircle } from 'lucide-react'
import { Card } from '@/components/ui/card'

/**
 * FetchArticleSpinner — shown while the Jina Reader extraction is in flight.
 */
export default function FetchArticleSpinner({ onCancel }) {
  return (
    <Card className="mb-6 py-8 bg-secondary border-border items-center text-center">
      <Loader2 className="size-8 text-primary animate-spin" />
      <p className="text-sm text-muted-foreground mt-2">正在获取原文内容...</p>
      {onCancel && (
        <button
          type="button"
          onClick={onCancel}
          className="mt-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive transition-colors cursor-pointer"
        >
          <XCircle className="size-3" />
          停止等待
        </button>
      )}
    </Card>
  )
}
