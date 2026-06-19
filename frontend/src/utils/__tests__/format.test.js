import { describe, it, expect } from 'vitest'
import { formatTime, formatTimestamp } from '../format'

describe('formatTime', () => {
  it('formats 0 seconds', () => {
    expect(formatTime(0)).toBe('0m 0s')
  })

  it('formats seconds only', () => {
    expect(formatTime(45)).toBe('0m 45s')
  })

  it('formats minutes and seconds', () => {
    expect(formatTime(125)).toBe('2m 5s')
  })

  it('formats hours, minutes and seconds', () => {
    expect(formatTime(3661)).toBe('1h 1m 1s')
  })
})

describe('formatTimestamp', () => {
  it('handles second-level timestamps', () => {
    const result = formatTimestamp(1700000000)
    expect(result).toBeTruthy()
    expect(typeof result).toBe('string')
  })

  it('handles millisecond-level timestamps', () => {
    const result = formatTimestamp(1700000000000)
    expect(result).toBeTruthy()
    expect(typeof result).toBe('string')
  })

  it('short mode returns first 8 chars', () => {
    const result = formatTimestamp(1700000000, { short: true })
    expect(result.length).toBeLessThanOrEqual(8)
  })
})
