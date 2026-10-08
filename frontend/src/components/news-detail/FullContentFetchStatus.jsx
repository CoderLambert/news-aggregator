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

function StatusAlert({ message, onRetry, showRetry = true, sourceUrl, retryLabel = '重试' }) {
  let safeSourceUrl = ''
  try {
    const parsed = new URL(sourceUrl)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') safeSourceUrl = parsed.href
  } catch {
    // Hide a malformed or non-web source URL.
  }

  return (
    <Alert variant="destructive" className="mb-6 border-red-200 bg-red-50">
      <AlertCircle />
      <AlertDescription className="flex flex-col gap-3 text-red-600 sm:flex-row sm:items-center sm:justify-between">
        <span>{message}</span>
        <div className="flex shrink-0 items-center gap-3">
          {safeSourceUrl && (
            <a href={safeSourceUrl} target="_blank" rel="noreferrer noopener" className="text-xs text-red-700 underline">
              阅读原文
            </a>
          )}
          {showRetry && (
            <Button
              type="button"
              variant="link"
              size="sm"
              onClick={() => onRetry()}
              className="h-auto self-start p-0 text-xs text-red-600 underline hover:no-underline sm:self-auto"
            >
              {retryLabel}
            </Button>
          )}
        </div>
      </AlertDescription>
    </Alert>
  )
}

export default function FullContentFetchStatus({ news, articleLoading, onFetch, onResume = onFetch, onCancel }) {
  if (!news) return null

  const status = articleLoading ? 'fetching' : (news.full_content_fetch_status || 'pending')
  const hasBody = Boolean(news.full_content?.trim())
  const hasTerminalError = !articleLoading && ['network_error', 'validation_failed', 'failed'].includes(status)
  if (hasBody && !hasTerminalError && status !== 'fetching') return null

  if (status === 'fetching' && articleLoading) return <FetchArticleSpinner onCancel={onCancel} />
  if (status === 'fetching') {
    return (
      <StatusAlert
        message="原文抓取仍在服务器运行；停止等待不会重复发起抓取。"
        onRetry={onResume}
        retryLabel="继续查看"
        sourceUrl={news.url}
      />
    )
  }
  if (status === 'pending' || status === 'idle') return <FetchArticleCard onFetch={onFetch} />
  if (status === 'network_error') {
    return <StatusAlert message={news.full_content_fetch_error?.trim() || STATUS_MESSAGES.network_error} onRetry={onFetch} sourceUrl={news.url} />
  }
  if (status === 'validation_failed') {
    return <StatusAlert message={news.full_content_fetch_error?.trim() || STATUS_MESSAGES.validation_failed} onRetry={onFetch} showRetry={false} sourceUrl={news.url} />
  }
  if (status === 'failed') {
    return <StatusAlert message={news.full_content_fetch_error?.trim() || STATUS_MESSAGES.failed} onRetry={onFetch} sourceUrl={news.url} />
  }

  return <FetchArticleCard onFetch={onFetch} />
}
