import { describe, expect, it } from 'vitest'
import {
  activeProcessStep,
  componentLabel,
  eventStatusLabel,
  eventTone,
  phaseLabel,
  timelineEventSummary,
  timelineEventTime,
  timelineEventTitle,
} from './timelinePresentation'

describe('runtime timeline presentation', () => {
  it('derives the active step from raw phases and component identifiers', () => {
    expect(activeProcessStep('autorealize', 'module.task_definition.evaluation_contract')).toBe('task_definition')
    expect(activeProcessStep('autorealize', 'stage.P1.file_reader')).toBe('data_cognition')
    expect(activeProcessStep('automl', '')).toBe('automl')
    expect(activeProcessStep('report', '')).toBe('report')
    expect(activeProcessStep('autorealize', 'module.unknown')).toBe('data_cognition')
  })

  it('translates component, phase and event protocol values for readers', () => {
    expect(componentLabel('module.data_cognition.relations')).toBe('分析数据表关联')
    expect(componentLabel('agent.some_internal_agent', 'automl')).toBe('算法分析')
    expect(phaseLabel('auto_ml')).toBe('方案搜索')
    expect(timelineEventTitle({ component: 'stage.P1', event: 'READ_COMPLETED' })).toBe('数据文件已读取')
    expect(timelineEventTitle({ component: 'module.data_cognition.relations', event: 'ACTIVATED' })).toBe(
      '分析数据表关联中',
    )
    expect(timelineEventTitle({ component: 'internal.worker', event: 'PRIVATE_ENUM' })).toBe('运行状态已更新')
  })

  it('shows a safe file summary without exposing its absolute path', () => {
    const summary = timelineEventSummary({
      status: 'completed',
      fields: { file: 'C:\\private\\input\\sales.csv', rows: 128, seconds: 1.26 },
    })

    expect(summary).toBe('sales.csv · 128行 · 耗时 1.3 秒')
    expect(summary).not.toContain('private')
  })

  it('labels failures and warnings by their human significance', () => {
    expect(eventStatusLabel({ status: 'failed', severity: 'error' })).toBe('失败')
    expect(eventStatusLabel({ status: 'info', severity: 'warning' })).toBe('需留意')
    expect(eventTone({ status: 'failed' })).toBe('failed')
    expect(eventTone({ severity: 'warning' })).toBe('warning')
    expect(timelineEventSummary({ status: 'failed', fields: {} })).toBe('展开技术详情查看错误信息。')
  })

  it('does not show machine payloads, traces or absolute paths as event titles', () => {
    expect(timelineEventTitle({ message: '{"internal":true}' })).toBe('运行状态已更新')
    expect(timelineEventTitle({ message: 'failed at C:\\private\\run\\file.py' })).toBe('运行状态已更新')
    expect(timelineEventTitle({ message: 'Traceback: internal stack' })).toBe('运行状态已更新')
  })

  it('formats timestamps for display and handles missing values', () => {
    expect(timelineEventTime('not-a-date')).toBe('时间未知')
    expect(timelineEventTime(null)).toBe('时间未知')
    expect(timelineEventTime('2026-10-27T00:00:00Z')).not.toBe('2026-10-27T00:00:00Z')
  })
})
