import { FileText, Download } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

/**
 * FetchArticleCard — "load full article via Jina Reader" CTA.
 *
 * Uses shadcn <Card> + <Button variant="indigo" size="pill">. The button
 * variant is project-specific (see ui/button.jsx) and preserves the
 * original indigo accent used for "fetch from source" affordances.
 */
export default function FetchArticleCard({ onFetch }) {
  return (
    <Card className="mb-6 gap-3 bg-gradient-to-r from-indigo-50 to-blue-50 border-indigo-100 py-4">
      <div className="flex items-center gap-3 px-4">
        <FileText className="size-5 text-indigo-500 shrink-0" />
        <div>
          <p className="text-sm font-medium text-gray-900">获取完整原文</p>
          <p className="text-xs text-gray-500">通过 Jina Reader 自动提取正文内容</p>
        </div>
      </div>
      <div className="px-4">
        <Button onClick={onFetch} aria-label="加载原文" variant="indigo" size="pill">
          <Download className="size-4" />
          加载原文
        </Button>
      </div>
    </Card>
  )
}
