/** A duration in words: "45 s", "3 min 20 s", "2 h 5 min", "3 d 4 h". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  const total = Math.max(0, Math.round(seconds))
  if (total < 60) return `${total} s`
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes} min ${total % 60} s`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} h ${minutes % 60} min`
  return `${Math.floor(hours / 24)} d ${hours % 24} h`
}

/** An ISO timestamp in the viewer's locale, or "—" when there is none. */
export function formatDateTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

/** Seconds from one ISO timestamp to another (to now when `to` is null). */
export function secondsBetween(from: string, to: string | null): number {
  const end = to === null ? Date.now() : new Date(to).getTime()
  return (end - new Date(from).getTime()) / 1000
}
