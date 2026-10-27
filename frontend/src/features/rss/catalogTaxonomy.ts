import { isRecord } from '@/types/news'

export interface CatalogGroup { key: string; label: string; count: number }
export interface CatalogSection extends CatalogGroup { groups: CatalogGroup[] }
export interface CatalogFilters { section: string; group: string; language: string; region: string }

export function parseCatalogSections(value: unknown): CatalogSection[] {
  // Additive contract: servers before the catalog upgrade have no sections.
  if (value === undefined) return []
  if (!Array.isArray(value) || value.length > 40) throw new TypeError('Invalid catalog sections')
  const keys = new Set<string>()
  const groupKeys = new Set<string>()
  const parseGroup = (item: unknown, seen: Set<string>): CatalogGroup => {
    if (!isRecord(item) || typeof item.key !== 'string' || !/^[a-z][a-z0-9-]{0,63}$/.test(item.key)
      || typeof item.label !== 'string' || !item.label.trim() || item.label.length > 40
      || typeof item.count !== 'number' || !Number.isSafeInteger(item.count) || item.count < 0
      || seen.has(item.key)) throw new TypeError('Invalid catalog group')
    seen.add(item.key)
    return { key: item.key, label: item.label, count: item.count }
  }
  return value.map(item => {
    const section = parseGroup(item, keys)
    if (!isRecord(item) || !Array.isArray(item.groups) || item.groups.length > 200) throw new TypeError('Invalid catalog groups')
    return { ...section, groups: item.groups.map(group => parseGroup(group, groupKeys)) }
  })
}
