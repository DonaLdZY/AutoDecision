import { describe, expect, it } from 'vitest'
import { deriveQdiLiveProgress, normalizeQdiQuestions } from './qdiPresentation'

describe('normalizeQdiQuestions', () => {
  it('merges planner questions, ledger records, and final answers', () => {
    const result = normalizeQdiQuestions({
      questions: [{ question_id: 'q1', question: '字段是否可关联？', priority: 'high' }],
      question_records: [{ question_id: 'q1', status: 'resolved', used_files: ['a.xlsx'] }],
      answers: [{ question_id: 'q1', answer: '覆盖率足够。', evidence: ['脚本统计'] }],
    })

    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({
      id: 'q1',
      status: 'resolved',
      answer: '覆盖率足够。',
      priority: 'high',
    })
    expect(result[0].evidence).toEqual(['脚本统计'])
    expect(result[0].usedFiles).toEqual(['a.xlsx'])
  })

  it('keeps legacy unresolved text visible as a question', () => {
    const result = normalizeQdiQuestions({
      unresolved_questions: ['缺少官方计费规则'],
    })

    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({
      question: '缺少官方计费规则',
      status: 'unresolved',
    })
  })
})

describe('deriveQdiLiveProgress', () => {
  it('builds useful live progress before the final QDI report exists', () => {
    const result = deriveQdiLiveProgress([
      {
        component: 'module.data_cognition.investigator',
        event: 'QUESTION_QUEUED',
        fields: { question_id: 'q1', question: '合同字段之间如何关联？', category: 'relation' },
        ts: '2026-07-14T06:00:00Z',
      },
      {
        component: 'module.data_cognition.investigator',
        event: 'QUESTION_STARTED',
        fields: { question_id: 'q1', question: '合同字段之间如何关联？' },
        ts: '2026-07-14T06:01:00Z',
      },
      {
        component: 'llm.client',
        event: 'REQUEST_STARTED',
        fields: { prompt: 'question_investigator_action' },
        ts: '2026-07-14T06:02:00Z',
      },
    ], {})

    expect(result.active).toBe(true)
    expect(result.currentQuestionId).toBe('q1')
    expect(result.eventQuestions[0].question).toBe('合同字段之间如何关联？')
    expect(result.activityLabel).toContain('下一步动作')
  })

  it('counts legacy QDI action calls when ACTION_SELECTED events are unavailable', () => {
    const result = deriveQdiLiveProgress([
      ...Array.from({ length: 3 }, (_, index) => ({
        component: 'llm.client',
        event: 'REQUEST_COMPLETED',
        fields: { prompt: 'question_investigator_action' },
        ts: `2026-07-14T06:0${index}:00Z`,
      })),
      {
        component: 'module.data_cognition.investigator',
        event: 'COMPLETED',
        fields: { questions: 1 },
        ts: '2026-07-14T06:04:00Z',
      },
    ], {})

    expect(result.actionDecisions).toBe(3)
    expect(result.completed).toBe(true)
  })
})
