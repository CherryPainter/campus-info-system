import { describe, it, expect } from 'vitest'
import { formatDateTime, formatDate, formatTimeShort } from '../datetime'

describe('formatDateTime', () => {
  it('将合法日期格式化为 YYYY-MM-DD HH:mm:ss', () => {
    expect(formatDateTime(new Date(2026, 6, 20, 8, 10, 0))).toBe('2026-07-20 08:10:00')
  })

  it('无效值（null/undefined/空串/非法串）统一返回 -', () => {
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime(undefined)).toBe('-')
    expect(formatDateTime('')).toBe('-')
    expect(formatDateTime('not-a-date')).toBe('-')
  })
})

describe('formatDate', () => {
  it('将合法日期格式化为 YYYY-MM-DD', () => {
    expect(formatDate(new Date(2026, 6, 20))).toBe('2026-07-20')
  })

  it('无效值返回 -', () => {
    expect(formatDate(null)).toBe('-')
  })
})

describe('formatTimeShort', () => {
  it('将合法日期格式化为 MM-DD HH:mm', () => {
    expect(formatTimeShort(new Date(2026, 6, 20, 8, 10))).toBe('07-20 08:10')
  })

  it('无效值返回 -', () => {
    expect(formatTimeShort('')).toBe('-')
  })
})
