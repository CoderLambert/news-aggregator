import { Loader2, XCircle } from 'lucide-react'
import { Card } from '@/components/ui/card'

/**
 * FetchArticleSpinner — shown while the Jina Reader extraction is in flight.
 */
export default function FetchArticleSpinner({ onCancel }) {
  return (
    <Card className="mb-6 py-8 bg-gray-50 border-gray-200 items-center text-center">
      <Loader2 className="size-8 text-indigo-500 animate-spin" />
      <p className="text-sm text-gray-500 mt-2">正在获取原文内容...</p>
      {onCancel && (
        <button
          type="button"
          onClick={onCancel}
          className="mt-3 inline-flex items-center gap-1 text-xs text-gray-400 hover:text-red-500 transition-colors cursor-pointer"
        >
          <XCircle className="size-3" />
          取消
        </button>
      )}
    </Card>
  )
}
