import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from '@playwright/test'

const base = process.env.AUTODECISION_UI_URL || 'http://127.0.0.1:5173'
const output = resolve('../../.codex-work/ui-verification')
const source = [
  '# Formula regression',
  'Inline: \\(x^2+y^2=z^2\\), $\\alpha+\\beta$.',
  '\\[\n\\operatorname{RMSE}=\\sqrt{\\frac{1}{n}\\sum_{i=1}^n(y_i-\\hat y_i)^2}\n\\]',
  '$$\n\\sum_{i=1}^{n} i=\\frac{n(n+1)}{2}\n$$',
  '| Metric | Definition |\n| --- | --- |\n| MAE | $\\frac{1}{n}\\sum_i \\lvert y_i\\rvert$ |',
  '\\[' + Array.from({ length: 45 }, () => 'x^2').join('+') + '\\]',
  '```latex\n\\[fenced_math\\]\n$code_only$\n```',
  '`\\(inline_code\\)`',
  '    \\[indented_code\\]',
  '<code>\\(html_code\\)</code>',
  '<script>window.__markdownPwned=true</script>',
  '<img onerror="window.__markdownPwned=true">',
  '<a href="https://example.com" onclick="window.__markdownPwned=true">safe link</a>',
  '[unsafe](javascript:alert(1))',
  '\\(\\href{javascript:alert(1)}{attack}\\)',
].join('\n\n')

await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { channel: 'msedge' } : {}) })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = [], requested = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => requested.push(request.url()))
  await page.goto(`${base}/?demo=1`)
  await page.locator('.graph-node').first().waitFor()
  assert.equal(requested.some(url => /markdownMath|katex/i.test(url)), false, 'Tree first screen must not load the math renderer')

  let releaseMath, notifyRequested
  const requestedMath = new Promise(done => { notifyRequested = done })
  const heldMath = new Promise(done => { releaseMath = done })
  await page.route(/\/src\/utils\/markdownMath\.ts(?:\?.*)?$/, async route => {
    notifyRequested()
    await heldMath
    await route.continue()
  })
  await page.evaluate(async () => {
    const { createApp, h, shallowRef } = await import('/node_modules/.vite/deps/vue.js')
    const { default: Report } = await import('/src/components/ReportDocument.vue')
    const { default: Artifact } = await import('/src/components/TaskArtifactPreview.vue')
    const root = document.createElement('div')
    root.id = 'markdown-regression'
    root.style.cssText = 'position:fixed;inset:0;z-index:10000;background:white;overflow:auto'
    document.body.append(root)
    const markdown = shallowRef('Future result \\[future_model=42\\]')
    window.__setMarkdown = value => { markdown.value = value }
    createApp({ render: () => h('div', [
      h(Report, { title: 'Formula regression', markdown: markdown.value, sections: [] }),
      h(Artifact, { snapshot: { auto_realize: { description_text: markdown.value } } }),
    ]) }).mount(root)
  })
  await requestedMath
  await page.evaluate(() => { window.__setMarkdown('Past frame without a model') })
  releaseMath()
  await page.evaluate(async () => { await import('/src/utils/markdownMath.ts') })
  const root = page.locator('#markdown-regression')
  assert.equal(await root.locator('.katex').count(), 0)
  assert.ok((await root.locator('.markdown-body').textContent()).includes('Past frame without a model'))
  assert.ok((await root.locator('.artifact-prose').textContent()).includes('Past frame without a model'))

  await page.evaluate(value => { window.__setMarkdown(value) }, source)
  await root.locator('.markdown-body .katex').first().waitFor()
  await root.locator('.artifact-prose .katex').first().waitFor()
  for (const selector of ['.markdown-body', '.artifact-prose']) {
    const rendered = root.locator(selector)
    assert.ok(await rendered.locator('.katex-display').count() >= 3)
    assert.ok(await rendered.locator('p .katex').count() >= 3)
    assert.equal(await rendered.locator('td .katex').count(), 1)
    assert.equal(await rendered.locator('code .katex').count(), 0)
    const code = (await rendered.locator('code').allTextContents()).join('\n')
    for (const expected of ['\\[fenced_math\\]', '$code_only$', '\\(inline_code\\)', '\\[indented_code\\]', 'html_code']) assert.ok(code.includes(expected), expected)
    assert.equal(await rendered.locator('script,iframe,[onerror],[onclick],a[href^="javascript:"]').count(), 0)
    assert.equal(await rendered.locator('.katex a').count(), 0)
    assert.ok(await rendered.locator('math').count() >= 5)
  }
  assert.equal(await page.evaluate(() => window.__markdownPwned), undefined)
  await page.evaluate(() => document.fonts.ready)
  assert.equal(await page.evaluate(() => document.fonts.check('16px KaTeX_Main')), true)
  await page.screenshot({ path: resolve(output, 'math-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await root.evaluate(element => element.scrollWidth <= element.clientWidth), true)
  await page.screenshot({ path: resolve(output, 'math-mobile.png') })

  const liveTaskName = process.env.AUTODECISION_MARKDOWN_LIVE_TASK
  let liveFormulaCount = null
  if (liveTaskName) {
    const live = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    live.on('pageerror', error => errors.push(error.message))
    await live.goto(base)
    const taskButton = live.getByRole('button').filter({ hasText: liveTaskName }).first()
    await taskButton.click()
    await live.getByRole('tab', { name: '报告生成', exact: true }).click()
    await live.locator('.markdown-body .katex-display').first().waitFor()
    liveFormulaCount = await live.locator('.markdown-body .katex-display').count()
    await live.evaluate(() => document.fonts.ready)
    await live.locator('.markdown-body .katex-display').first().scrollIntoViewIfNeeded()
    await live.screenshot({ path: resolve(output, 'math-live-report.png') })
    await live.close()
  }
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ passed: true, delayedMathDoesNotRestoreFutureDocument: true, codePreserved: true, unsafeHtmlRemoved: true, firstTreeScreenLoadsMath: false, liveFormulaCount, screenshots: output, browserErrors: errors }))
} finally { await browser.close() }
