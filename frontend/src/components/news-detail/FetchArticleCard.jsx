import { FileText, Download } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

/**
 * FetchArticleCard — "load full article via Jina Reader" CTA.
 */
export default function FetchArticleCard({ onFetch }) {
  return (
    <Card className="mb-6 gap-2 border-indigo-100 bg-gradient-to-r from-indigo-50/80 to-white px-4 py-4 shadow-none sm:px-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-indigo-100">
            <FileText className="size-4 text-indigo-600" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-neutral-900">当前仅有摘要</p>
            <p className="mt-1 text-xs leading-5 text-neutral-500">获取完整原文后，可保留段落、列表、代码并使用全文翻译。</p>
          </div>
        </div>
        <Button onClick={() => onFetch()} variant="indigo" size="sm" className="h-10 rounded-full px-4 sm:self-center">
          <Download className="size-3.5" />
          获取完整原文
        </Button>
      </div>
    </Card>
  )
}
