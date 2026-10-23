/**
 * Unknown bulk outcome barrier.
 *
 * A bulk group request whose response was lost may still have been applied by
 * the server, so the owner must re-read their groups and subscriptions before
 * any further write. The record lives outside React state: leaving and
 * re-entering the page (or a remount) must not silently drop the barrier and
 * let the next bulk action retry blindly.
 */
const uncertainViewers = new Set<number>()

export function isBulkUncertain(viewer: number): boolean {
  return uncertainViewers.has(viewer)
}

export function markBulkUncertain(viewer: number): void {
  uncertainViewers.add(viewer)
}

export function clearBulkUncertain(viewer: number): void {
  uncertainViewers.delete(viewer)
}
