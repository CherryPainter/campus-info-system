import { describe, it, expect } from 'vitest'
import { getSemesterStartDate, getWeekDate } from '../semester'

describe('getSemesterStartDate', () => {
  it('第一学期 20251 -> 2025-09-01', () => {
    const d = getSemesterStartDate(20251)
    expect(d.getFullYear()).toBe(2025)
    expect(d.getMonth()).toBe(8) // 9 月（0 基）
    expect(d.getDate()).toBe(1)
  })

  it('第二学期 20252 -> 2026-03-02', () => {
    const d = getSemesterStartDate(20252)
    expect(d.getFullYear()).toBe(2026)
    expect(d.getMonth()).toBe(2) // 3 月（0 基）
    expect(d.getDate()).toBe(2)
  })
})

describe('getWeekDate', () => {
  it('20251 第 1 周周一 -> 09-01', () => {
    expect(getWeekDate(1, 1, 20251)).toBe('09-01')
  })

  it('20251 第 2 周周一 -> 09-08（按 7 天递进）', () => {
    expect(getWeekDate(2, 1, 20251)).toBe('09-08')
  })

  it('20251 第 1 周周三 -> 09-03', () => {
    expect(getWeekDate(1, 3, 20251)).toBe('09-03')
  })
})
