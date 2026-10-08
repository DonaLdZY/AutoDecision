import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from '@playwright/test'

const base = process.env.AUTODECISION_UI_URL || 'http://127.0.0.1:5173'
const output = resolve('../../.codex-work/recovery-verification')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { channel: 'msedge' } : {}) })
try {
  const seed = await browser.newPage()
  await seed.goto(`${base}/?demo=1`)
  const fixture = await seed.evaluate(async () => {
    const data = await import('/src/utils/demoRecording.ts')
    return { task: data.demoTask, snapshot: data.demoSnapshot }
  })
  await seed.close()
  for (const scenario of ['completed', 'report_failed', 'definition_failed']) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.stack))
    const task = { ...fixture.task, id: 'recovery-fixture', task_name: 'Recovery fixture',
      status: scenario === 'completed' ? 'completed' : 'failed',
      phase: scenario === 'definition_failed' ? 'prepare_automl_input_failed' : scenario,
      auto_ml_log_dir: scenario === 'definition_failed' ? null : '/fixture/automl/logs/run',
      auto_ml_workspace_dir: scenario === 'definition_failed' ? null : '/fixture/automl/workspaces/run',
      run_dir: '/fixture/task', config: { ...fixture.task.config, task_name: 'Recovery fixture' } }
    const submitted = []
    await page.route('**/api/**', async route => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      let data = {}
      if (path === '/api/tasks') data = [task]
      else if (path === '/api/fs/roots') data = { roots: [] }
      else if (path === '/api/fs/list') data = { path: '/fixture', children: [] }
      else if (path.endsWith('/snapshot')) data = { ...fixture.snapshot, task,
        automl_readiness: { ready: false, can_repair_review: true, review_issues: ['stale review'] } }
      else if (path.endsWith('/review-repair-plan')) data = {
        plan_token: 'confirmed-current-manifest', replace_paths: ['/fixture/task/autorealize'],
        delete_paths: [], archive_root: '/fixture/task/stage-history', preserve_paths: ['/fixture/task/autorealize/realize_report/data_description.md'],
        files: Array.from({ length: 200 }, (_, i) => ({ path: `autorealize/realize_report/document-${i}.json`, size: 4000 })),
      }
      else if (path.endsWith('/repair-review-and-resume')) {
        submitted.push(request.postDataJSON())
        data = { status: 'started' }
      } else if (request.method() === 'PUT') data = task
      await route.fulfill({ json: data })
    })
    await page.goto(base)
    await page.getByRole('button', { name: '任务配置', exact: true }).click()
    const repair = page.getByRole('button', { name: '修复审查并继续', exact: true })
    if (scenario !== 'definition_failed') {
      await repair.waitFor()
      assert.equal(await repair.isDisabled(), true)
    } else {
      await repair.click()
      const dialog = page.getByRole('dialog', { name: '确认修复范围' })
      await dialog.waitFor()
      assert.equal(submitted.length, 0)
      assert.ok((await dialog.innerText()).includes('永久删除：无'))
      assert.ok((await dialog.innerText()).includes('document-199.json'))
      await page.screenshot({ path: resolve(output, 'confirmation-desktop.png') })
      await page.setViewportSize({ width: 390, height: 844 })
      await page.screenshot({ path: resolve(output, 'confirmation-mobile.png') })
      const bounds = await dialog.boundingBox()
      assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 844)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      await dialog.getByRole('button', { name: '取消', exact: true }).click()
      assert.equal(submitted.length, 0)
      await page.setViewportSize({ width: 1440, height: 1000 })
      await repair.click()
      await dialog.getByRole('button', { name: '确认范围并修复', exact: true }).click()
      await page.waitForTimeout(100)
      assert.deepEqual(submitted, [{ task_id: task.id, confirm: true, plan_token: 'confirmed-current-manifest' }])
    }
    assert.deepEqual(errors, [])
    await page.close()
  }
  if (process.env.CHECK_DELIVERY_REPORT === '1') {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    await page.goto(base)
    await page.getByRole('button', { name: /城配订单运力匹配/ }).first().click()
    await page.getByRole('tab', { name: '报告生成', exact: true }).click()
    const report = page.locator('.markdown-body')
    await report.waitFor()
    assert.ok((await report.innerText()).includes('任务定义版本'))
    assert.ok((await report.innerText()).includes('1820.0421425016427'))
    await page.screenshot({ path: resolve(output, 'delivery-report-desktop.png') })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: resolve(output, 'delivery-report-mobile.png') })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await page.close()
  }
  console.log(JSON.stringify({ passed: true, scenarios: 3, screenshots: output }))
} finally {
  await browser.close()
}
