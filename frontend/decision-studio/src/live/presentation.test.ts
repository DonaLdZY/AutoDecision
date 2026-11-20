import { describe, expect, it } from 'vitest'
import { candidatePlan, candidateReadiness, candidateSummary, formatDate, humanApiError, humanFinalEvaluationStatus, humanPhase, humanReportStatus, humanTaskStatus, inputSummary, projectDescription, resourceSummary, summarizeGoal, taskResourceSummary, usageSummary, webResearchSummary } from './presentation'

describe('human-facing summaries', () => {
  it('turns real validation payloads into field guidance without echoing raw inputs', () => {
    expect(humanApiError([{ type: 'missing', loc: ['body', 'input_root'], input: 'private-path' }], 422)).toBe('数据目录尚未填写。')
    expect(humanApiError([{ type: 'greater_than_equal', loc: ['body', 'auto_ml', 'time_limit_secs'], input: -1 }], 422)).toContain('搜索时间超出')
    expect(humanApiError({ unexpected: { private: true } }, 502)).not.toContain('private')
    expect(humanApiError('{"detail":[{"type":"missing","loc":["body","text"]}]}', 422)).toBe('需求尚未填写。')
    expect(humanApiError('模型服务暂时不可用，请稍后重试。', 502)).toContain('模型服务')
  })
  it('hides internal project-registration copy while preserving user descriptions', () => {
    expect(projectDescription('从已有任务登记的数据项目；运行证据取自任务实际产物。')).toBe('本地数据项目')
    expect(projectDescription('硫酸铝压滤工序实时数据')).toBe('硫酸铝压滤工序实时数据')
  })
  it('condenses a long task request without losing its first complete sentence', () => {
    const goal = '预测下一小时压滤液结果，并推荐蒸汽进气流量。' + '补充约束。'.repeat(40)
    expect(summarizeGoal(goal, 30)).toBe('预测下一小时压滤液结果，并推荐蒸汽进气流量。')
  })

  it('formats numeric and ISO timestamps without exposing invalid date strings', () => {
    expect(formatDate(1_800_000_000)).not.toBe('时间未知')
    expect(formatDate(1_800_000_000_000)).not.toBe('时间未知')
    expect(formatDate('2026-10-23T00:00:00.000Z')).toContain('2026')
    expect(formatDate('Invalid Date')).toBe('时间未知')
    expect(formatDate(undefined)).toBe('时间未知')
  })

  it('describes project inputs without exposing source paths or field mappings', () => {
    expect(inputSummary({
      input_mode: 'project',
      input_summary: { source_count: 3, row_count: 1250, first_observation: '2026-10-01', last_observation: '2026-10-22', cutoff: '2026-10-23 10:00' },
    })).toEqual(['本地项目数据 · 3 个数据源 · 1,250 条记录', '观测范围：2026-10-01 至 2026-10-22 · 数据截止：2026-10-23 10:00'])
  })

  it('uses a simple label when the input did not come from project data', () => {
    expect(inputSummary({ input_mode: 'previous' })).toEqual(['接收上一环节结果'])
  })

  it('reads candidate reviews as objects and encoded JSON without displaying the protocol', () => {
    expect(candidateSummary({ result: { summary: '误差下降，保留此方案。', metric: 0.1 } })).toBe('误差下降，保留此方案。')
    expect(candidateSummary({ result: '{"summary":"缺少输入列。","is_bug":true}' })).toBe('缺少输入列。')
    expect(candidateSummary({ insight: { summary: '已完成人工复核。' }, result: '其他信息' })).toBe('已完成人工复核。')
    expect(candidateSummary({ result: { error: { message: '数据类型不匹配。' } } })).toBe('数据类型不匹配。')
  })

  it('keeps unknown or broken machine outputs out of the readable summary', () => {
    for (const result of [{ metric: 0 }, '[{"metric":0}]', '{broken', null]) {
      expect(candidateSummary({ result, is_buggy: true })).toBe('方案检查未通过，可查看详情。')
    }
    expect(candidateSummary({ metric: 0, result: {} })).toBe('已完成开发集评估。')
    expect(candidateSummary({ result: {} })).toBe('正在等待评估结果。')
  })

  it('extracts actual stored diff plans instead of showing escaped JSON and code', () => {
    const plan = '{"reason":"\\u4fee\\u590d\\u65e9\\u505c\\u76ee\\u6807","module":"def train(): pass","parse_success":true,"raw_response":"internal protocol"}'
    expect(candidatePlan({ plan })).toBe('修复早停目标')
    expect(candidatePlan({ plan: { plan: '比较树模型与线性模型。', raw_response: 'secret' } })).toBe('比较树模型与线性模型。')
    expect(candidatePlan({ plan: '{"raw_response":"do not show","module":"import os"}' })).not.toContain('raw_response')
    expect(candidatePlan({ plan: 'def train():\n    pass' })).not.toContain('def train')
  })

  it('shows usage with an honest zero cache hit and no fabricated counts', () => {
    expect(usageSummary({ prompt_tokens: 1000, completion_tokens: 50, prompt_tokens_details: { cached_tokens: 0 } })).toEqual([
      { label: '输入', value: '1,000 tokens' }, { label: '输出', value: '50 tokens' }, { label: '模型输入缓存', value: '0.0%' },
    ])
    expect(usageSummary({ prompt_tokens: 1000, prompt_cache_hit_tokens: 750 })[1]?.value).toBe('75.0%')
    expect(usageSummary({ total_tokens: 200, prompt_tokens: -1 })).toEqual([])
  })

  it('describes actual resources and missing hardware without a JSON dump', () => {
    expect(resourceSummary({ cpu: { logical_count: 20, physical_count: 12 }, memory: { total_gb: 31.35 }, devices: [{ name: 'GPU', memory_mb: 16384, runtime_available: true }] })).toEqual([
      { label: '处理器', value: '20 个逻辑核心 · 12 个物理核心' }, { label: '内存', value: '31.4 GB' }, { label: '加速设备', value: 'GPU · 16.0 GB 显存' },
    ])
    expect(resourceSummary({ devices: [] }).at(-1)?.value).toBe('未检测到，将使用 CPU')
  })

  it('turns task resource settings into a readable summary', () => {
    expect(taskResourceSummary({ cpu_cores: 8, memory_limit_gb: 10, accelerator_mode: 'none' }))
      .toBe('8 核处理器 · 10 GB 内存上限 · 仅使用 CPU')
    expect(taskResourceSummary({ accelerator_mode: 'selected' })).toBe('使用指定加速设备')
  })

  it('maps internal lifecycle values to reader-facing status labels', () => {
    expect(humanTaskStatus('no_eligible_candidate')).toBe('状态更新中')
    expect(humanTaskStatus('completed')).toBe('已完成')
    expect(humanPhase('automl_completed')).toBe('方案搜索已完成')
    expect(humanFinalEvaluationStatus('no_eligible_candidate')).toBe('目前没有符合交付条件的方案')
    expect(humanReportStatus('blocked')).toBe('报告交付需要处理')
  })

  it('summarizes candidate readiness without exposing gate field names', () => {
    expect(candidateReadiness({ delivery_certified: true })).toEqual({ label: '已通过交付检查', tone: 'success' })
    expect(candidateReadiness({ is_buggy: true })).toEqual({ label: '需要修正', tone: 'warning' })
    expect(candidateReadiness({ runtime_ok: false, is_buggy: false })).toEqual({ label: '需要修正', tone: 'warning' })
    expect(candidateReadiness({ metric: 0.2 })).toEqual({ label: '等待检查', tone: 'neutral' })
  })

  it('summarizes public web research without exposing the query or machine metrics', () => {
    expect(webResearchSummary(false, { status: 'success' })).toBeNull()
    expect(webResearchSummary(true, {
      status: 'success',
      elapsed_ms: 1240,
      search: { accepted_count: 2, source_hosts: ['scikit-learn.org', 'xgboost.readthedocs.io'] },
      fetch_attempts: [{ status: 'success' }],
      query_sha256: 'private-query-fingerprint',
    })).toEqual([
      { label: '状态', value: '找到 2 条公开参考资料' },
      { label: '耗时', value: '1.2 秒' },
      { label: '已读取网页', value: '1' },
      { label: '来源网站', value: 'scikit-learn.org · xgboost.readthedocs.io' },
    ])
    expect(webResearchSummary(true, { status: 'error' })?.[0]?.value).toContain('方案搜索继续')
  })
})
