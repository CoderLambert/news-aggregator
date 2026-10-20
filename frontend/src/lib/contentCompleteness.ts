/** Readability never proves that the publisher supplied the entire article. */
export function contentCompletenessLabel(readable: boolean, completeness?: string): string {
  if (!readable || completeness === 'summary') return '仅摘要'
  return completeness === 'verified' ? '已确认全文' : '已获取内容，完整性未确认'
}
