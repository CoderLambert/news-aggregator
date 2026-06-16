import { AlertCircle } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import FetchArticleCard from './FetchArticleCard'
import FetchArticleSpinner from './FetchArticleSpinner'

const STATUS_MESSAGES = {
  network_error: '网络或源站暂不可达，可稍后重试',
  validation_failed: '抓取内容未通过真实性校验，等待规则优化',
  failed: '原文抓取失败，请稍后重试',
}

function StatusAlert({ message, onRetry, showRetry = true }) {
  return (
    <Alert variant="destructive" className="mb-6 border-red-200 bg-red-50">
      <AlertCircle />
      <AlertDescription className="flex flex-col gap-3 text-red-600 sm:flex-row sm:items-center sm:justify-between">
        <span>{message}</span>
        {showRetry && (
          <Button
            type="button"
            variant="link"
            size="sm"
            onClick={onRetry}
            className="h-auto self-start p-0 text-xs text-red-600 underline hover:no-underline sm:self-auto"
          >
            重试
          </Button>
        )}
      </AlertDescription>
    </Alert>
  )
}

export default function FullContentFetchStatus({ news, articleLoading, onFetch, onCancel }) {
  if (!news || news.source_language !== 'en' || news.full_content) return null

  const status = articleLoading ? 'fetching' : (news.full_content_fetch_status || 'pending')

  if (status === 'fetching') return <FetchArticleSpinner onCancel={onCancel} />
  if (status === 'pending' || status === 'idle') return <FetchArticleCard onFetch={onFetch} />
  if (status === 'network_error') {
    return <StatusAlert message={STATUS_MESSAGES.network_error} onRetry={onFetch} />
  }
  if (status === 'validation_failed') {
    return <StatusAlert message={STATUS_MESSAGES.validation_failed} onRetry={onFetch} showRetry={false} />
  }
  if (status === 'failed') {
    return <StatusAlert message={STATUS_MESSAGES.failed} onRetry={onFetch} />
  }

  return <FetchArticleCard onFetch={onFetch} />
}
