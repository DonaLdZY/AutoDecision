import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

function pending<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept
    reject = fail
  })
  return { promise, resolve, reject }
}
function workspace(title: string) {
  return {
    projects: [{ id: 'project', name: 'Test' }],
    archived_projects: [],
    packages: [],
    tasks: [],
    links: [],
    invocations: [],
    conversations: [{ id: title, project_id: 'project', title, messages: [] }],
  }
}
function response(title: string) {
  return { ok: true, json: async () => workspace(title) } as Response
}

beforeEach(() => {
  vi.resetModules()
  vi.stubGlobal('location', { hash: '#chat' })
  vi.stubGlobal('localStorage', { getItem: () => '', setItem: vi.fn() })
  vi.stubGlobal('sessionStorage', { getItem: () => '' })
  vi.stubGlobal('window', { addEventListener: vi.fn() })
})
afterEach(() => vi.unstubAllGlobals())

describe('workspace refresh after conversation changes', () => {
  it('fetches after a mutation while polling is pending and rejects stale poll results', async () => {
    const poll = pending<Response>(),
      mutation = pending<Response>()
    vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(poll.promise).mockReturnValueOnce(mutation.promise))
    const { refresh, state, ui } = await import('./store')
    const older = refresh(true),
      newer = refresh()
    mutation.resolve(response('remaining-conversation'))
    await newer
    expect(state.conversations.map((item) => item.id)).toEqual(['remaining-conversation'])
    poll.resolve(response('deleted-conversation'))
    await older
    expect(state.conversations.map((item) => item.id)).toEqual(['remaining-conversation'])
    expect(ui.conversationId).toBe('remaining-conversation')
    expect(ui.online).toBe(true)
  })
  it('ignores an old network failure after the authoritative refresh succeeds', async () => {
    const poll = pending<Response>()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockReturnValueOnce(poll.promise).mockResolvedValueOnce(response('restored')),
    )
    const { refresh, state, ui } = await import('./store')
    const older = refresh(true)
    await refresh()
    poll.reject(new TypeError('old connection closed'))
    await older
    expect(ui.online).toBe(true)
    expect(ui.error).toBe('')
    expect(state.conversations[0]?.id).toBe('restored')
  })
})

describe('conversations across project data', () => {
  it('keeps tab order fixed and follows the project of the selected conversation', async () => {
    const saved = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => saved.get(key) || '',
      setItem: (key: string, value: string) => saved.set(key, value),
    })
    const { state, ui, conversations, selectConversation, selectProject } = await import('./store')
    state.conversations = [
      { id: 'b', project_id: 'one', title: 'B', messages: [], created_at: 2, updated_at: 100 },
      { id: 'a', project_id: 'one', title: 'A', messages: [], created_at: 1, updated_at: 10 },
      { id: 'c', project_id: 'two', title: 'C', messages: [], created_at: 3 },
    ]
    expect(conversations.value.map((item) => item.id)).toEqual(['a', 'b', 'c'])
    selectConversation('b')
    state.conversations[1]!.updated_at = 500
    expect(conversations.value.map((item) => item.id)).toEqual(['a', 'b', 'c'])
    expect(ui.projectId).toBe('one')
    selectConversation('c')
    expect(ui.projectId).toBe('two')
    expect(saved.get('studio.conversation')).toBe('c')
    selectProject('one')
    expect(ui.conversationId).toBe('b')
    selectConversation('a')
    selectProject('one')
    expect(ui.conversationId).toBe('a')
    expect(saved.get('studio.project')).toBe('one')
  })
  it('opens project data when no page was requested', async () => {
    vi.stubGlobal('location', { hash: '' })
    const { ui } = await import('./store')
    expect(ui.page).toBe('projects')
  })
})
