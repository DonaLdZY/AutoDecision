import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'

const base = process.env.AUTODECISION_UI_URL || 'http://127.0.0.1:5173'
const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { channel: 'msedge' } : {}) })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(`${base}/?demo=1`)
  await page.locator('.graph-node').first().waitFor()
  await page.evaluate(async () => {
    const { createApp, h, shallowRef } = await import('/node_modules/.vite/deps/vue.js')
    const { default: Tree } = await import('/src/components/MctsSearchTree.vue')
    const root = document.createElement('div')
    root.style.cssText = 'position:fixed;inset:0;z-index:10000;background:white'
    document.body.append(root)
    const all = Array.from({ length: 1000 }, (_, index) => ({ id: `candidate-${index}`, parent_id: index ? `candidate-${Math.floor((index - 1) / 3)}` : null, stage: 'draft', metric: index }))
    const nodes = shallowRef(all)
    window.__setGraphCount = count => { nodes.value = all.slice(0, count) }
    const NativeWorker = window.Worker
    window.__holdGraphWorker = false
    window.__releaseGraphWorkers = []
    window.Worker = class {
      constructor(url, options) {
        this.worker = new NativeWorker(url, options)
        this.worker.onmessage = event => {
          if (window.__holdGraphWorker) window.__releaseGraphWorkers.push(() => this.onmessage?.(event))
          else this.onmessage?.(event)
        }
        this.worker.onerror = event => this.onerror?.(event)
      }
      postMessage(message) { this.worker.postMessage(message) }
      terminate() { this.worker.terminate() }
    }
    createApp({ render: () => h(Tree, { nodes: nodes.value }) }).mount(root)
    root.id = 'worker-regression'
  })
  const tree = page.locator('#worker-regression')
  await tree.locator('.graph-node').nth(999).waitFor()
  assert.equal(await tree.locator('.graph-minimap > rect:not(.graph-minimap-window)').count(), 1000)
  await page.evaluate(() => { window.__holdGraphWorker = true; window.__setGraphCount(300) })
  await tree.locator('.graph-layout-pending').waitFor()
  assert.equal(await tree.locator('.graph-node').count(), 300)
  assert.equal(await tree.locator('.graph-minimap > rect:not(.graph-minimap-window)').count(), 300)
  await page.waitForFunction(() => window.__releaseGraphWorkers.length > 0)
  await page.evaluate(() => { window.__setGraphCount(50) })
  await tree.locator('.graph-layout-pending').waitFor({ state: 'hidden' })
  await page.evaluate(() => { window.__holdGraphWorker = false; window.__releaseGraphWorkers.splice(0).forEach(release => release()) })
  assert.equal(await tree.locator('.graph-node').count(), 50)
  assert.equal(await tree.locator('.graph-minimap > rect:not(.graph-minimap-window)').count(), 50)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ passed: true, backwardsSeek: [1000, 300, 50], futureNodesVisibleWhileWorkerPending: false, browserErrors: errors }))
} finally { await browser.close() }
