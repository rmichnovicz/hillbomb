import { describe, it, expect } from 'vitest'
import { gradeToColor, GRADE_STOPS, flowGradeColor } from '../../utils/gradeColor'

describe('gradeToColor', () => {
  it('returns the first stop color for grade 0', () => {
    expect(gradeToColor(0)).toBe(GRADE_STOPS[0].color)
  })

  it('uses absolute value — negative grade (downhill) maps same as positive', () => {
    expect(gradeToColor(-0.10)).toBe(gradeToColor(0.10))
  })

  it('returns a steeper color for 12% than for 5%', () => {
    const c5 = gradeToColor(0.05)
    const c12 = gradeToColor(0.12)
    // They must be different colors — steeper = different bucket
    expect(c12).not.toBe(c5)
  })

  it('caps at the maximum stop for extreme grades', () => {
    const verySteeply = gradeToColor(0.99)
    const atMax = gradeToColor(GRADE_STOPS[GRADE_STOPS.length - 1].grade)
    expect(verySteeply).toBe(atMax)
  })

  it('returns a valid hex or rgb color string', () => {
    const color = gradeToColor(0.08)
    expect(color).toMatch(/^#[0-9a-fA-F]{6}$|^rgb/)
  })

  it('returns a color for each defined stop grade', () => {
    for (const stop of GRADE_STOPS) {
      expect(gradeToColor(stop.grade)).toBeTruthy()
    }
  })

  it('grade just below a threshold uses the lower bucket color', () => {
    const threshold = GRADE_STOPS[1].grade  // e.g. 0.04
    const belowColor = gradeToColor(threshold - 0.001)
    const atColor    = gradeToColor(threshold)
    // At threshold should be same or higher bucket; below should be lower bucket
    expect(belowColor).toBe(GRADE_STOPS[0].color)
    expect(atColor).toBe(GRADE_STOPS[1].color)
  })
})

describe('flowGradeColor', () => {
  it('returns a color for every valid grade letter', () => {
    for (const grade of ['A', 'B', 'C', 'D', 'E', 'F']) {
      expect(flowGradeColor(grade)).toMatch(/^#[0-9a-fA-F]{6}$|^rgb/)
    }
  })

  it('A is a different color from F', () => {
    expect(flowGradeColor('A')).not.toBe(flowGradeColor('F'))
  })

  it('returns a fallback for unknown grades', () => {
    expect(flowGradeColor('Z')).toBeTruthy()
  })
})
