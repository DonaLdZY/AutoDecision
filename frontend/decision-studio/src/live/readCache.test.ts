import { describe, expect, it, vi } from 'vitest'
import { createReadCache } from './readCache'

describe('inspection reads', () => {
  it('joins concurrent reads, reuses a successful read, and refreshes after expiry', async () => {
    let clock = 0
    const cache = createReadCache(() => clock)
    const load = vi.fn(async () => ({ ready: true }))
    const [a, b] = await Promise.all([cache.read('task:a', load, 10), cache.read('task:a', load, 10)])
    expect(a).toBe(b)
    await cache.read('task:a', load, 10)
    expect(load).toHaveBeenCalledTimes(1)
    clock = 11
    await cache.read('task:a', load, 10)
    expect(load).toHaveBeenCalledTimes(2)
  })
  it('allows an explicit refresh and does not retain failures', async () => {
    const cache = createReadCache()
    const load = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(2)
    await expect(cache.read('task:a', load)).rejects.toThrow('offline')
    expect(await cache.read('task:a', load)).toBe(2)
    await cache.read('task:a', load, 30000, true)
    expect(load).toHaveBeenCalledTimes(3)
  })
  it('invalidates by revision without an older pending read overwriting newer data', async () => {
    const cache = createReadCache()
    let finish!: (value: number) => void
    const old = cache.read('task:a', () => new Promise<number>(resolve => { finish = resolve }))
    await Promise.resolve()
    cache.invalidate('task:')
    expect(await cache.read('task:a', async () => 2)).toBe(2)
    finish(1)
    await old
    expect(await cache.read('task:a', async () => 3)).toBe(2)
  })
})
