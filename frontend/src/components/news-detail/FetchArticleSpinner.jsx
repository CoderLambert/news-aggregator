import { Loader2 } from 'lucide-react'
import { Card } from '@/components/ui/card'

/**
 * FetchArticleSpinner — shown while the Jina Reader extraction is in flight.
 */
export default function FetchArticleSpinner() {
  return (
    <Card className="mb-6 py-8 bg-gray-50 border-gray-200 items-center text-center">
      <Loader2 className="size-8 text-indigo-500 animate-spin" />
      <p className="text-sm text-gray-500">正在获取原文内容...</p>
    </Card>
  )
}
