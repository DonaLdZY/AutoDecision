import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from '@playwright/test'

const base = process.env.INDUSTRIAL_UI_URL || 'http://127.0.0.1:5173'
const taskId = process.env.INDUSTRIAL_TASK_ID || '3369088f116a4ff7a7a04acf035f5b3a'
const output = resolve('../../.codex-work/industrial-replay', taskId, String(Date.now()))
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { channel: 'msedge' } : {}) })
const errors = []
const timings = []
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(base)
  const tasks = await (await page.request.get(`${base}/api/tasks`)).json()
  const task = tasks.find(item => item.id === taskId)
  assert.ok(task, 'Real industrial task must exist')
  const taskName = task.task_name.replace(/^工业实例[\s_-]*/, '')
  await page.locator('.task-select').filter({ hasText: taskName }).click()
  await page.getByRole('heading', { name: taskName, exact: true }).waitFor()
  assert.equal(await page.title(), '工智寻优')
  assert.equal(await page.locator('.task-select').filter({ hasText: '工业实例' }).count(), 0)
  await page.getByRole('button', { name: '任务重放', exact: true }).click()
  await page.getByRole('region', { name: '任务重放控制' }).waitFor()
  const recording = await (await page.request.get(`${base}/api/tasks/${taskId}/replay`)).json()
  assert.ok(recording.events.length > 0)
  const snapshot = await (await page.request.get(`${base}/api/tasks/${taskId}/snapshot`)).json()
  const winner = snapshot.auto_ml.best_node_id
  assert.ok(winner, 'Task snapshot must identify a best node')
  const firstWinnerIndex = recording.events.findIndex(event => event.payload.node?.id === winner)
  assert.ok(firstWinnerIndex > 0)
  const offsets = await page.evaluate(async recording => {
    const replay = await import('/src/utils/replay.ts')
    return replay.playbackOffsets(recording.events, 'nodes', 1000)
  }, recording)
  const controls = page.getByRole('region', { name: '任务重放控制' })
  await controls.getByRole('checkbox', { name: '跟随阶段', exact: true }).uncheck()
  const interval = page.getByRole('spinbutton', { name: '节点间隔（毫秒）', exact: true })
  assert.equal(await interval.inputValue(), '1000')
  const track = page.getByRole('slider', { name: '重放进度', exact: true })
  const seek = async value => {
    const start = performance.now()
    await track.evaluate((element, value) => {
      element.value = String(value)
      element.dispatchEvent(new Event('input', { bubbles: true }))
    }, value)
    timings.push(performance.now() - start)
  }
  const duration = Number(await track.getAttribute('max'))
  await seek(duration)
  await page.getByRole('tab', { name: '自动机器学习', exact: true }).click()
  await page.getByRole('button', { name: '定位最佳方案', exact: true }).click()
  await page.locator(`.graph-node[title^="${winner}"]`).waitFor()
  await page.getByRole('button', { name: '代码', exact: true }).click()
  await page.locator('.inspector-code').waitFor()
  await page.getByRole('button', { name: '概览', exact: true }).click()
  const candidateCount = (snapshot.auto_ml.nodes ?? []).filter(node => node.stage !== 'root').length
  assert.match(await page.locator('.search-counters').innerText(), new RegExp(`候选\\s+${candidateCount}(?:\\s|$)`))
  await page.screenshot({ path: resolve(output, 'desktop-final-tree.png'), fullPage: true, animations: 'disabled' })
  await seek(offsets[firstWinnerIndex] - 1)
  assert.equal(await page.locator(`.graph-node[title^="${winner}"]`).count(), 0)
  await seek(0)
  assert.equal(await page.locator('.graph-node').count(), 0)
  await page.getByRole('button', { name: '下一事件', exact: true }).click()
  await page.getByRole('button', { name: '上一事件', exact: true }).click()
  await page.getByRole('combobox', { name: '播放倍速', exact: true }).selectOption('2')
  await page.getByRole('button', { name: '播放重放', exact: true }).click()
  await page.waitForTimeout(200)
  await page.getByRole('button', { name: '暂停重放', exact: true }).click()
  const paused = await track.inputValue()
  await page.waitForTimeout(100)
  assert.equal(await track.inputValue(), paused)
  await page.getByRole('button', { name: '原始时间', exact: true }).click()
  assert.ok(Number(await track.getAttribute('max')) >= recording.duration_ms - 2)
  await page.getByRole('button', { name: '节点节奏', exact: true }).click()
  await seek(duration)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(180)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
  await page.screenshot({ path: resolve(output, 'mobile-final-tree.png'), fullPage: true, animations: 'disabled' })
  await page.screenshot({ path: resolve(output, 'mobile-viewport.png'), animations: 'disabled' })
  assert.equal(await interval.isVisible(), true)
  assert.equal(await page.getByRole('combobox', { name: '播放倍速', exact: true }).isVisible(), true)
  const reportCompleted = task.phase === 'report_completed' && task.status === 'completed'
  if (reportCompleted) {
    await page.getByRole('tab', { name: '报告生成', exact: true }).click()
    await page.locator('.markdown-body').waitFor()
    assert.ok((await page.locator('.markdown-body').innerText()).length > 100)
    await page.screenshot({ path: resolve(output, 'mobile-report.png'), fullPage: true })
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.screenshot({ path: resolve(output, 'desktop-report.png'), fullPage: true })
  }
  assert.deepEqual(errors, [])
  const result = { passed: true, taskId, reportCompleted, events: recording.events.length,
    fidelity: recording.fidelity, originalDurationMs: recording.duration_ms, nodeDurationMs: duration,
    seekRoundtripMs: timings, newNodeIntervalMs: 1000, browserErrors: errors, output }
  await writeFile(resolve(output, 'result.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
} finally {
  await browser.close()
}
