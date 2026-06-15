/**
 * Grade → color mapping. Single source of truth shared by map layer paint
 * expressions, Chart.js bar colors, and sparkline SVGs.
 * Do not hardcode these values elsewhere.
 */

export interface GradeStop {
  grade: number  // absolute grade threshold (e.g. 0.04 = 4%)
  color: string  // hex color
}

export const GRADE_STOPS: GradeStop[] = [
  { grade: 0.00, color: '#4ade80' },  // green  — flat / very gentle
  { grade: 0.04, color: '#a3e635' },  // lime   — mild
  { grade: 0.07, color: '#facc15' },  // yellow — moderate
  { grade: 0.10, color: '#fb923c' },  // orange — steep
  { grade: 0.14, color: '#f87171' },  // red    — very steep
  { grade: 0.18, color: '#dc2626' },  // dark red — extreme
]

/** Map an absolute grade fraction to a display color. Uses abs value so
 *  downhill (negative) and uphill (positive) get the same color bucket. */
export function gradeToColor(grade: number): string {
  const abs = Math.abs(grade)
  let color = GRADE_STOPS[0].color
  for (const stop of GRADE_STOPS) {
    if (abs >= stop.grade) {
      color = stop.color
    }
  }
  return color
}

const FLOW_GRADE_COLORS: Record<string, string> = {
  A: '#4ade80',  // green
  B: '#a3e635',  // lime
  C: '#facc15',  // yellow
  D: '#fb923c',  // orange
  E: '#f87171',  // red
  F: '#dc2626',  // dark red
}

/** Map a flow grade letter (A–F) to a display color. */
export function flowGradeColor(grade: string): string {
  return FLOW_GRADE_COLORS[grade] ?? '#9ca3af'  // gray fallback for unknown
}
