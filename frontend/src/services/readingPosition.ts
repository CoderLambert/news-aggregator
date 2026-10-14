/** Ephemeral per-viewer reading navigation position. No cross-account persistence. */
export interface ReadingPosition {
  top: number
  articleId: string
  offset: number
}

const memory = new Map<string, ReadingPosition>()
const MAX_POSITION_RECORDS = 32

export function positionKey(viewerId: number | string, pathname: string, search: string): string {
  return JSON.stringify([viewerId, pathname, search])
}

export function rememberReadingPosition(
  viewerId: number | string, pathname: string, search: string, position: ReadingPosition,
): void {
  const key = positionKey(viewerId, pathname, search)
  memory.delete(key)
  memory.set(key, position)
  while (memory.size > MAX_POSITION_RECORDS) {
    const oldest = memory.keys().next().value
    if (oldest === undefined) break
    memory.delete(oldest)
  }
}

export function readingPosition(viewerId: number | string, pathname: string, search: string): ReadingPosition | undefined {
  return memory.get(positionKey(viewerId, pathname, search))
}

export function clearReadingPositions(): void {
  memory.clear()
}
