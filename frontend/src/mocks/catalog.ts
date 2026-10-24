/** Network behavior only. User-visible expectations belong in the independent test matrix. */
export interface Scenario {
  id: string
  label: string
  list: 'normal' | 'empty' | 'error' | 'retry' | 'slow' | 'network-error' | 'malformed' | 'race' | 'rate-limited'
  detail: 'normal' | 'missing' | 'summary-only'
  read: 'normal' | 'save-error' | 'conflict' | 'load-retry'
  identity: 'member' | 'expired'
  capabilities: 'full' | 'read-only' | 'unavailable'
}
function scenario(id: string, label: string, changes: Partial<Omit<Scenario, 'id' | 'label'>> = {}): Readonly<Scenario> {
  return Object.freeze({ id, label, list: 'normal', detail: 'normal', read: 'normal', identity: 'member', capabilities: 'full', ...changes })
}
export const scenarios: readonly Readonly<Scenario>[] = Object.freeze([
  scenario('normal', '正常阅读与已读保存'),
  scenario('news-empty', '新闻列表为空', { list: 'empty' }),
  scenario('news-error', '新闻服务持续失败', { list: 'error' }),
  scenario('news-retry', '自动重试耗尽后，手动重试恢复', { list: 'retry' }),
  scenario('news-slow', '新闻列表延迟 1500ms', { list: 'slow' }),
  scenario('news-network-error', '连接失败而非 HTTP 500', { list: 'network-error' }),
  scenario('news-malformed', '必需字段缺失', { list: 'malformed' }),
  scenario('news-rate-limited', '429 与 Retry-After', { list: 'rate-limited' }),
  scenario('search-race', '旧搜索慢、新搜索快', { list: 'race' }),
  scenario('detail-not-found', '文章已不可访问', { detail: 'missing' }),
  scenario('summary-only', '仅摘要、无正文授权', { detail: 'summary-only' }),
  scenario('read-save-error', '已读保存失败、不能假成功', { read: 'save-error' }),
  scenario('read-conflict', '其他设备更新、版本冲突、重新读取', { read: 'conflict' }),
  scenario('read-load-retry', '读取状态失败后重试', { read: 'load-retry' }),
  scenario('auth-expired', '会话过期、个人接口拒绝', { identity: 'expired' }),
  scenario('read-only', '公共只读、隐藏个人写操作', { capabilities: 'read-only' }),
  scenario('capabilities-unavailable', '能力读取失败、不能开放个人操作', { capabilities: 'unavailable' }),
])
export function getScenario(id: string): Readonly<Scenario> {
  const found = scenarios.find(item => item.id === id)
  if (!found) throw new Error(`Unknown scenario: ${id}. Available: ${scenarios.map(s => s.id).join(', ')}`)
  return found
}
