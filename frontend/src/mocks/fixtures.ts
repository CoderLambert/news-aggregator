/** Synthetic, intentionally small DTOs pinned to the real contracts. No real articles or credentials. */
export const MOCK_VIEWER = Object.freeze({ id: 79001, username: 'scenario-reader', is_superuser: false,
  rss_capabilities: { review_public_rss: false, manage_rss_reviewers: false, reviewer_version: 0 } })
export const MOCK_CSRF = 'newshub-synthetic-token-not-a-real-session'
export const FIXED_TIME = '2026-10-20T08:00:00Z'
// Kept independent of services/api.ts. Contract tests compare this set to CAPABILITY_FEATURE_NAMES.
export const MOCK_FEATURE_NAMES = [
  'news', 'keyword_search', 'semantic_search', 'accounts', 'signup', 'favorites', 'blocked_news',
  'chat_history', 'fetch_full', 'translation', 'chat', 'suggested_questions', 'tts', 'research',
  'research_byok_create', 'provider_comparisons', 'admin', 'chatgpt_subscription',
] as const
export function capabilityFixture(readOnly: boolean) {
  const enabled = new Set(['news', 'keyword_search', ...(!readOnly ? ['accounts'] : [])])
  const features = Object.fromEntries(MOCK_FEATURE_NAMES.map(name => [name, {
    enabled: enabled.has(name), reason: enabled.has(name) ? null : readOnly ? 'public_read_only' : 'capabilities_unavailable',
  }]))
  return { site_mode: readOnly ? 'read_only' : 'full', chatgpt_auth_mode: 'disabled', features }
}
export function sourceFixtures() {
  return [
    { id: 101, name: 'Scenario Engineering', region: 'international', language: 'en', source_type: 'news',
      description: '合成前端工程频道', can_subscribe: true, rss_status: 'active', subscription_status: 'active',
      subscription_reason: '', news_count: 1, reading_policy: 'standard', url: 'https://engineering.invalid/',
      feed_url: 'https://engineering.invalid/feed.xml', logo: '', topics: ['frontend'], origin: 'catalog',
      needs_review: false, evidence_hash: 'synthetic', policy_key: 'synthetic', updated_at: FIXED_TIME },
    { id: 102, name: 'Scenario Weekly', region: 'domestic', language: 'zh', source_type: 'news',
      description: '合成周刊频道', can_subscribe: true, rss_status: 'active', subscription_status: 'active',
      subscription_reason: '', news_count: 1, reading_policy: 'standard', url: 'https://weekly.invalid/',
      feed_url: 'https://weekly.invalid/feed.xml', logo: '', topics: ['frontend'], origin: 'catalog',
      needs_review: false, evidence_hash: 'synthetic', policy_key: 'synthetic', updated_at: FIXED_TIME },
  ]
}
export function summaryFixtures() {
  return ['场景测试：前端接口契约', '场景测试：阅读状态同步'].map((title, index) => ({
    id: 910001 + index, title, title_zh: title, summary: '这是一条合成摘要，用于测试真实 NewsHub 页面。',
    summary_zh: '这是一条合成摘要，用于测试真实 NewsHub 页面。', author: 'Scenario Lab',
    publish_time: FIXED_TIME, created_at: FIXED_TIME, publish_time_inferred: false,
    source: 101 + index, source_name: index ? 'Scenario Weekly' : 'Scenario Engineering',
    source_region: index ? 'domestic' : 'international', source_type: 'news', source_language: 'zh',
    category: 201, category_name: '前端工程', url: `https://articles.invalid/${910001 + index}`, cover_image: null,
    related_to: null, channel_ids: [101 + index], channel_names: [index ? 'Scenario Weekly' : 'Scenario Engineering'],
    reading_policy: 'standard', body_access_granted: true, can_fetch_full_content: false, can_rss_refetch: false,
    translation_status: 'completed', translation_error: '', translation_retry_count: 0,
    full_content_fetch_status: 'completed', full_content_fetch_error: '', full_content_fetch_provider: 'miniflux',
    full_content_quality_score: 1, full_content_retry_count: 0, last_full_content_attempt: FIXED_TIME,
    has_full_content: true, content_kind: 'article', full_content_state: 'complete', full_content_revision: 1,
    full_content_completeness: 'verified', body_owner: 'miniflux', full_content_next_attempt_at: null, full_content_error_code: '',
  }))
}
export function detailFixture(id: number, summaryOnly: boolean) {
  const summary = summaryFixtures().find(item => item.id === id)
  if (!summary) return null
  const content = '# 合成文章正文\n\n本文仅用于本地场景开发，不来自真实用户或外部抓取。\n\n接口字段经过现有解析器后进入页面。'
  return { ...summary,
    content: summaryOnly ? summary.summary : content, content_zh: summaryOnly ? summary.summary_zh : content,
    source_url: summary.url, full_content: summaryOnly ? '' : content,
    full_content_fetched_at: summaryOnly ? null : FIXED_TIME,
    full_content_zh: '', full_content_zh_fetched_at: null, full_content_zh_source: null,
    full_content_zh_scope: null, full_content_zh_result_id: null, full_content_zh_task_id: null,
    full_content_zh_model: null, full_content_zh_current_match: null, full_content_zh_private_history: [],
    full_translation_personal_available: false, full_translation_active: false,
    ...(summaryOnly ? { reading_policy: 'rss_summary_only', body_access_granted: false,
      has_full_content: false, full_content_state: 'summary', full_content_completeness: 'summary' } : {}),
  }
}
export const rootFixtures = () => [{ id: 301, name: '工程学习', version: 1, child_count: 1, created_at: FIXED_TIME, updated_at: FIXED_TIME }]
export const groupFixtures = () => [{ id: 401, root_id: 301, name: '前端', source_ids: [101], version: 1, created_at: FIXED_TIME, updated_at: FIXED_TIME }]
export const subscriptionFixtures = () => [{ id: 501, source_id: 101, group_ids: [401], category_id: null, category_version: 0 }]
export function statsFixture(count: number) {
  return { today: count, total: count, streak: count ? 1 : 0, timezone: 'Asia/Shanghai',
    week: Array.from({ length: 7 }, (_, index) => ({ day: `2026-10-${14 + index}`, count: index === 6 ? count : 0 })) }
}
