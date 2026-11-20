type Entry<T> = { value?: T; expires: number; pending?: Promise<T> }

/** Short-lived read cache. Concurrent readers share one request; failed reads never stick. */
export function createReadCache(now = Date.now, capacity = 48) {
  const entries = new Map<string, Entry<unknown>>()
  function read<T>(key: string, loader: () => Promise<T>, ttl = 30000, force = false): Promise<T> {
    const existing = entries.get(key) as Entry<T> | undefined
    if (existing?.pending) return existing.pending
    if (!force && existing && existing.expires > now()) return Promise.resolve(existing.value as T)
    const entry: Entry<T> = { expires: 0 }
    entry.pending = Promise.resolve().then(loader).then(value => {
      if (entries.get(key) === entry) {
        entry.value = value
        entry.expires = now() + ttl
        entry.pending = undefined
      }
      return value
    }, error => {
      if (entries.get(key) === entry) entries.delete(key)
      throw error
    })
    entries.set(key, entry)
    if (entries.size > capacity) entries.delete(entries.keys().next().value!)
    return entry.pending
  }
  function invalidate(prefix = '') {
    for (const key of entries.keys()) if (key.startsWith(prefix)) entries.delete(key)
  }
  return { read, invalidate }
}

export const inspectionReads = createReadCache()
