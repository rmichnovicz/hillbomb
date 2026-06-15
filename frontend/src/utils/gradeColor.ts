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
  for (let i = GRADE_STOPS.length - 1; i >= 0; i--) {
    if (abs >= GRADE_STOPS[i].grade) return GRADE_STOPS[i].color
  }
  return GRADE_STOPS[0].color
}

// Flow grades A–F map onto the grade stops gentle→steep, so derive them from
// the single GRADE_STOPS source rather than repeating the hex values.
const FLOW_GRADE_COLORS: Record<string, string> = Object.fromEntries(
  ['A', 'B', 'C', 'D', 'E', 'F'].map((letter, i) => [letter, GRADE_STOPS[i].color]),
)

/** Map a flow grade letter (A–F) to a display color. */
export function flowGradeColor(grade: string): string {
  return FLOW_GRADE_COLORS[grade] ?? '#9ca3af'  // gray fallback for unknown
}
