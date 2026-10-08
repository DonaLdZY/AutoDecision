import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { shallowRef, toValue, watch, type MaybeRefOrGetter } from 'vue'

const mathDelimiter = /\$|\\[[(]/
let mathRenderer: Promise<typeof import('./markdownMath')> | undefined

export function renderPlainMarkdown(source: string): string {
  return DOMPurify.sanitize(marked.parse(source, { async: false, breaks: false }))
}

export function renderSafeMarkdown(source: string): string | Promise<string> {
  if (!mathDelimiter.test(source)) return renderPlainMarkdown(source)
  mathRenderer ??= import('./markdownMath').catch(error => { mathRenderer = undefined; throw error })
  return mathRenderer.then(module => DOMPurify.sanitize(module.renderMathMarkdown(source)))
}

export function useSafeMarkdown(source: MaybeRefOrGetter<string>) {
  const html = shallowRef('')
  watch(() => toValue(source), (value, _previous, onCleanup) => {
    let current = true
    onCleanup(() => { current = false })
    const result = renderSafeMarkdown(value)
    if (typeof result === 'string') { html.value = result; return }
    // Never leave the previous document visible while a new replay frame awaits math assets.
    html.value = ''
    void result.then(rendered => { if (current) html.value = rendered })
      .catch(() => { if (current) html.value = renderPlainMarkdown(value) })
  }, { immediate: true, flush: 'sync' })
  return html
}
