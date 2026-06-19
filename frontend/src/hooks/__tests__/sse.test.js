import { describe, it, expect } from 'vitest'
import { formatSSEEvent } from '../../utils/sse'

describe('formatSSEEvent', () => {
  it('maps "done" status to logStatus "done"', () => {
    const result = formatSSEEvent({ status: 'done', timestamp: 1000 })
    expect(result.status).toBe('done')
    expect(result.message).toBe('完成')
    expect(result.timestamp).toBe(1000)
  })

  it('maps "error" status to logStatus "error"', () => {
    const result = formatSSEEvent({ status: 'error', message: '出错了', timestamp: 2000 })
    expect(result.status).toBe('error')
    expect(result.message).toBe('错误: 出错了')
  })

  it('maps "chapter_writing" status to logStatus "start"', () => {
    const result = formatSSEEvent({ status: 'chapter_writing', chapter: 3 })
    expect(result.status).toBe('start')
    expect(result.message).toBe('正在撰写第 3 章')
  })

  it('maps "cycle_cancelled" status to logStatus "error"', () => {
    const result = formatSSEEvent({ status: 'cycle_cancelled' })
    expect(result.status).toBe('error')
    expect(result.message).toBe('已取消')
  })

  it('maps "cycle_stuck" status to logStatus "warning"', () => {
    const result = formatSSEEvent({ status: 'cycle_stuck' })
    expect(result.status).toBe('warning')
  })

  it('maps "reviewer_done" with score and issues', () => {
    const result = formatSSEEvent({ status: 'reviewer_done', score: 8, issues: ['问题1', '问题2', '问题3', '问题4'] })
    expect(result.status).toBe('done')
    expect(result.message).toContain('8/10')
    expect(result.message).toContain('问题1')
    // 只显示前3个 issues
    expect(result.message).not.toContain('问题4')
  })

  it('falls back to data.message for unknown status', () => {
    const result = formatSSEEvent({ status: 'unknown_status', message: '自定义消息' })
    expect(result.message).toBe('自定义消息')
  })

  it('uses current timestamp when not provided', () => {
    const before = Date.now()
    const result = formatSSEEvent({ status: 'info', message: 'test' })
    const after = Date.now()
    expect(result.timestamp).toBeGreaterThanOrEqual(before)
    expect(result.timestamp).toBeLessThanOrEqual(after)
  })

  it('preserves role from data', () => {
    const result = formatSSEEvent({ status: 'info', role: '系统', message: 'hello' })
    expect(result.role).toBe('系统')
  })

  it('maps "outline_layer_done" with layer info', () => {
    const result = formatSSEEvent({ status: 'outline_layer_done', layer: 'L2' })
    expect(result.status).toBe('done')
    expect(result.message).toBe('L2 大纲完成')
  })
})
