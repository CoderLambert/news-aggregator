/** Never label an inferred first-seen timestamp as the publisher's date. */
export function formatUnverifiedNewsTime(value: string, mode: 'compact' | 'full'): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '发表时间未核实'
  const observed = mode === 'full'
    ? date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })
    : date.toLocaleDateString('zh-CN')
  return `站内收录：${observed}（发表时间未核实）`
}
