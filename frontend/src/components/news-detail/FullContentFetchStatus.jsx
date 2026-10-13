import { AlertCircle } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import FetchArticleCard from './FetchArticleCard'
import FetchArticleSpinner from './FetchArticleSpinner'
import { hasReadableFullContent, hasPendingFullContentTask } from '@/types/news'

const STATUS_MESSAGES = {
  network_error: '网络或源站暂不可达，可稍后重试',
  validation_failed: '抓取内容未通过真实性校验，等待规则优化',
  failed: '原文抓取失败，请稍后重试',
}

function StatusAlert({ message, onRetry, showRetry = true, sourceUrl, retryLabel = '重试', title = '未能保存完整原文', helperText = '你仍可阅读下方摘要，或直接前往来源网站。' }) {
  let safeSourceUrl = ''
  try {
    const parsed = new URL(sourceUrl)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') safeSourceUrl = parsed.href
  } catch {
    // Hide a malformed or non-web source URL.
  }

  return (
    <Alert variant="default" className="mb-6 grid-cols-[2rem_minmax(0,1fr)] items-start gap-x-3 border-amber-200 bg-amber-50/70 px-4 py-4 text-amber-950 sm:px-5">
      <span className="mt-0.5 flex size-8 items-center justify-center rounded-full bg-amber-100">
        <AlertCircle className="size-4 text-amber-700" />
      </span>
      <AlertDescription className="min-w-0 text-amber-950">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold">{title}</p>
            <p className="mt-1 break-words text-sm leading-6 text-amber-900/80">{message}</p>
            <p className="mt-1 text-xs text-amber-800/70">{helperText}</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
          {safeSourceUrl && (
            <a href={safeSourceUrl} target="_blank" rel="noreferrer noopener" className="inline-flex h-10 items-center rounded-full border border-amber-300 bg-white px-4 text-xs font-medium text-amber-900 transition-colors hover:bg-amber-100">
              阅读原文
            </a>
          )}
          {showRetry && (
            <Button
              type="button"
              variant="link"
              size="sm"
              onClick={() => onRetry()}
              className="h-10 rounded-full bg-amber-900 px-4 text-xs font-medium text-white no-underline hover:bg-amber-800 hover:text-white"
            >
              {retryLabel}
            </Button>
          )}
          </div>
        </div>
      </AlertDescription>
    </Alert>
  )
}

export default function FullContentFetchStatus({ news, articleLoading, onFetch, onResume = onFetch, onCancel }) {
  if (!news) return null

  if (news.reading_policy === 'rss_summary_only') {
    return <StatusAlert title="RSS 摘要阅读" message="该频道仅提供标题、摘要和原文链接，不在站内获取正文。" helperText="完整内容请前往来源网站，部分内容可能需要订阅。" sourceUrl={news.url} showRetry={false} />
  }
  if (news.reading_policy === 'public_rss' && !hasReadableFullContent(news)) {
    return <StatusAlert title="RSS 资讯" message="当前展示来源 RSS 公开提供的内容。" helperText="更多内容请前往来源网站阅读。" sourceUrl={news.url} showRetry={false} />
  }

  if (news.full_content_error_code === 'invalid_identity') {
    return <StatusAlert title="链接待核验" message="来源文章身份尚未核验，当前保留摘要供阅读。" helperText="核验真实链接后才能获取原文。" showRetry={false} />
  }

  const pending = hasPendingFullContentTask(news)
  const status = articleLoading && !pending ? 'fetching' : (news.full_content_fetch_status || 'pending')
  const hasBody = hasReadableFullContent(news)
  const helperText = hasBody
    ? '上次保存的正文仍可阅读，也可直接前往来源网站。'
    : '你仍可阅读下方摘要，或直接前往来源网站。'
  const failureTitle = hasBody ? '本次原文更新未完成' : '未能保存完整原文'
  const hasTerminalError = !articleLoading && ['network_error', 'validation_failed', 'failed'].includes(status)
  if (hasBody && !hasTerminalError && !pending && !articleLoading) return null
  if (news.full_content_retry_count >= 5) {
    return <StatusAlert title="正文尝试已达上限" message="来源获取连续失败，当前任务已停止。" helperText={helperText} sourceUrl={news.url} showRetry={false} />
  }

  if (pending && status !== 'fetching') {
    const cooling = ['rate_limited', 'network_error', 'failed'].includes(status)
    return <StatusAlert title={cooling ? '正文任务等待重试' : '正文任务已排队'}
      message={cooling ? '来源暂时限流或任务正在等待到期；到期后服务器会继续处理。' : '服务器会按来源顺序和到期时间获取正文。'}
      onRetry={articleLoading ? onCancel : onResume} retryLabel={articleLoading ? '停止等待' : '继续查看'}
      sourceUrl={news.url} helperText={hasBody ? '上次保存的正文仍可阅读；停止等待不会撤销共享任务。' : '当前可阅读摘要；停止等待不会撤销共享任务。'} />
  }

  if (status === 'fetching' && articleLoading) return <FetchArticleSpinner onCancel={onCancel} />
  if (status === 'fetching') {
    return (
      <StatusAlert
        title={hasBody ? '原文仍在服务器更新' : '原文仍在服务器获取'}
        message="原文抓取仍在服务器运行；停止等待不会重复发起抓取。"
        onRetry={onResume}
        retryLabel="继续查看"
        sourceUrl={news.url}
        helperText={helperText}
      />
    )
  }
  if (status === 'pending' || status === 'idle') return <FetchArticleCard onFetch={onFetch} />
  if (status === 'network_error') {
    return <StatusAlert title={failureTitle} message={news.full_content_fetch_error?.trim() || STATUS_MESSAGES.network_error} onRetry={onFetch} sourceUrl={news.url} helperText={helperText} />
  }
  if (status === 'validation_failed') {
    return <StatusAlert title={failureTitle} message={news.full_content_fetch_error?.trim() || STATUS_MESSAGES.validation_failed} onRetry={onFetch} showRetry={false} sourceUrl={news.url} helperText={helperText} />
  }
  if (status === 'failed') {
    return <StatusAlert title={failureTitle} message={news.full_content_fetch_error?.trim() || STATUS_MESSAGES.failed} onRetry={onFetch} sourceUrl={news.url} helperText={helperText} />
  }
  if (status === 'blocked' || status === 'unsupported' || status === 'rate_limited') {
    return <StatusAlert title={failureTitle} message="该来源当前无法获取正文，请前往来源网站阅读。" showRetry={false} sourceUrl={news.url} helperText={helperText} />
  }

  return <FetchArticleCard onFetch={onFetch} />
}
