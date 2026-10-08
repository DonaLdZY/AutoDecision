import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from '@playwright/test'

const base = process.env.AUTODECISION_UI_URL || 'http://127.0.0.1:5173'
const output = resolve('../../.codex-work/replay-focus')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { channel: 'msedge' } : {}) })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = [], mutations = []
  page.on('pageerror', error => errors.push(error.message))
  let fixture
  await page.route('**/api/**', async route => {
    const request = route.request()
    if (request.method() !== 'GET') mutations.push(request.method())
    const path = new URL(request.url()).pathname
    let data = {}
    if (path === '/api/tasks') data = fixture ? [fixture.task] : []
    else if (path.endsWith('/snapshot')) data = fixture.snapshot
    else if (path.endsWith('/replay')) data = fixture.recording
    else if (path === '/api/fs/roots') data = { roots: [] }
    else if (path === '/api/fs/list') data = { path: '/fixture', children: [] }
    await route.fulfill({ json: data })
  })
  await page.goto(`${base}/?demo=1`)
  fixture = await page.evaluate(async () => {
    const { demoTask } = await import('/src/utils/demoRecording.ts')
    const { projectReplay } = await import('/src/utils/replay.ts')
    const task = { ...demoTask, id: 'replay-focus-fixture', task_name: 'Replay focus fixture' }
    const rows = [
      ['data_cognition', { task: { status: 'running', phase: 'autorealize' } }],
      ['task_definition', { event: { event: 'STARTED', component: 'module.task_definition' } }],
      ['data_cognition', { snapshot: { auto_realize: { data_description_text: '# Data evidence' } } }],
      ['task_definition', { event: { event: 'PROGRESS' } }],
      ['data_cognition', { snapshot: { auto_realize: { automl_context_text: '# Context milestone' } } }],
      ['task_definition', { event: { event: 'REVIEW_STARTED' } }],
      ['data_cognition', { snapshot: { auto_realize: { current_state: { status: 'running' } } } }],
      ['task_definition', { snapshot: { auto_realize: { description_text: '# Description milestone' } } }],
      ['data_cognition', { snapshot: { auto_realize: { automl_context_text: '# Revised context' } } }],
      ['automl', { task: { status: 'running', phase: 'automl' } }],
      ['data_cognition', { snapshot: { auto_realize: { description_text: '# Revised description' } } }],
      ['report', { task: { status: 'completed', phase: 'report_completed' }, snapshot: { auto_report: { report_markdown: '# Final report' } } }],
    ]
    const events = rows.map(([stage, payload], index) => ({ sequence: index + 1, timestamp: 1000 + index,
      offset_ms: index * 1000, stage, payload, label: `event-${index + 1}`,
      kind: payload.snapshot ? 'artifact' : payload.event ? 'event' : 'stage' }))
    const recording = { schema_version: 1, task_id: task.id, task_name: task.task_name, fidelity: 'recorded',
      fidelity_notes: [], started_at: 1000, ended_at: 1011, duration_ms: 11000, events }
    return { task, recording, snapshot: projectReplay(recording, events.length - 1, task) }
  })
  await page.goto(base)
  await page.getByRole('button', { name: '任务重放', exact: true }).click()
  const controls = page.getByRole('region', { name: '任务重放控制' })
  await controls.waitFor()
  const follow = controls.getByRole('checkbox', { name: '跟随阶段', exact: true })
  const track = page.getByRole('slider', { name: '重放进度', exact: true })
  const assertStage = async name => assert.equal(await page.getByRole('tab', { name, exact: true }).getAttribute('aria-selected'), 'true')
  const assertArtifact = async name => assert.equal(await page.getByRole('tab', { name, exact: true }).getAttribute('aria-selected'), 'true')
  const seek = async value => {
    await track.evaluate((element, ms) => {
      element.value = String(ms)
      element.dispatchEvent(new Event('input', { bubbles: true }))
    }, value)
    await page.waitForFunction(() => !!document.querySelector('[aria-label="任务重放控制"]'))
  }
  const expected = ['数据理解', '数据理解', '数据理解', '数据理解', '任务定义', '任务定义', '任务定义', '任务定义', '任务定义', '自动机器学习', '自动机器学习', '报告生成']
  for (const mode of ['节点节奏', '原始时间']) {
    await page.getByRole('button', { name: mode, exact: true }).click()
    await page.getByRole('button', { name: '回到开始', exact: true }).click()
    for (let i = 0; i < expected.length; i++) {
      if (i) await page.getByRole('button', { name: '下一事件', exact: true }).click()
      await assertStage(expected[i])
      if (i >= 4 && i <= 6) await assertArtifact('automl_context.md')
      if (i === 7 || i === 8) await assertArtifact('description.md')
    }
  }
  await seek(4000)
  await assertStage('任务定义')
  await assertArtifact('automl_context.md')
  await page.screenshot({ path: resolve(output, 'context-desktop.png') })
  await page.getByRole('tab', { name: '数据理解', exact: true }).click()
  assert.equal(await follow.isChecked(), false)
  await seek(7000)
  await assertStage('数据理解')
  await follow.check()
  await assertStage('任务定义')
  await assertArtifact('description.md')
  await page.getByRole('tab', { name: 'main_task_protocol.json', exact: true }).click()
  await seek(8000)
  await assertArtifact('main_task_protocol.json')
  await seek(4000)
  await assertArtifact('automl_context.md')
  await page.setViewportSize({ width: 390, height: 844 })
  await seek(7000)
  await assertArtifact('description.md')
  await page.screenshot({ path: resolve(output, 'description-mobile.png'), fullPage: true })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.getByRole('button', { name: '回到开始', exact: true }).click()
  await assertStage('数据理解')
  await page.getByRole('combobox', { name: '播放倍速', exact: true }).selectOption('2')
  await page.getByRole('button', { name: '播放重放', exact: true }).click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '暂停重放', exact: true }).click()
  await assertStage('数据理解')
  assert.deepEqual(errors, [])
  assert.deepEqual(mutations, [])
  console.log(JSON.stringify({ passed: true, modes: 2, eventsPerMode: expected.length, browserErrors: errors, output }))
} finally {
  await browser.close()
}
