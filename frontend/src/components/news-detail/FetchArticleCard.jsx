import { FileText, Download } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

/**
 * FetchArticleCard — "load full article via Jina Reader" CTA.
 */
export default function FetchArticleCard({ onFetch }) {
  return (
    <Card className="mb-8 gap-2 bg-gradient-to-b from-indigo-50/80 to-white border-indigo-100/60 py-5 px-5">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center size-9 rounded-xl bg-indigo-100 shrink-0">
          <FileText className="size-4 text-indigo-600" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-neutral-900">获取完整原文</p>
          <p className="text-xs text-neutral-400 mt-0.5">自动提取正文内容，支持 AI 翻译</p>
        </div>
        <Button onClick={onFetch} aria-label="加载原文" variant="indigo" size="pill-sm">
          <Download className="size-3.5" />
          加载原文
        </Button>
      </div>
    </Card>
  )
}
