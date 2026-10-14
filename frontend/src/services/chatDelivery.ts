import { isRecord } from '@/types/news'

export type ChatCompletionStatus = 'complete' | 'interrupted' | 'failed' | 'legacy_unknown'
export interface ChatDeliveryMetadata { contract?: 2; status?: ChatCompletionStatus; saved?: boolean }

export function parseChatDeliveryMetadata(text: string): ChatDeliveryMetadata | null {
  let value: unknown
  try { value = JSON.parse(text) } catch { return null }
  if (!isRecord(value)) return null
  if (value.type === 'article_context' && value.delivery_contract === 2) return { contract: 2 }
  if (value.type !== 'chat_status') return null
  const status = value.status
  if (status !== 'complete' && status !== 'interrupted' && status !== 'failed') return null
  return { status, saved: value.saved === true }
}

export function completionLabel(status: ChatCompletionStatus | undefined): string {
  if (status === 'complete') return ''
  if (status === 'interrupted') return '回答已中断，以下内容未完整生成。'
  if (status === 'failed') return '回答生成失败，以下内容不是完整结论。'
  return '历史回答的完成状态未验证。'
}
