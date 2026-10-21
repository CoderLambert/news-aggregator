/** Explicit publisher avatar labels must not use article-photo presentation. */
export function isAvatarAlt(alt: string | undefined) {
  return /(?:\bavatar|头像)\s*$/i.test(alt ?? '')
}
