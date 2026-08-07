/**
 * The route's OSM `mtb:scale` grade, as a small S0–S6 chip.
 *
 * Renders NOTHING when the grade is null, and that is the whole design of this
 * component. Null means *no segment on the route carried a difficulty tag*, which is
 * the common case — most trails, and every paved road, are untagged. Showing "S0" or
 * "—" there would put a difficulty claim on 30-odd road descents that have nothing to
 * do with mountain biking, and would read as "this trail is easy" rather than "nobody
 * has graded this trail". Absent is the honest rendering of absent.
 *
 * See backend/config.py SAC_SCALE_TO_DIFFICULTY for how the grade is derived.
 */

/** Singletrail-Skala, 0-6. Kept short — this sits in a 11px row next to four other stats. */
const GRADE_TITLE: Record<number, string> = {
  0: 'S0 — smooth doubletrack or fire road',
  1: 'S1 — small obstacles, loose surface',
  2: 'S2 — bigger roots and rocks, some steps',
  3: 'S3 — large obstacles, tight switchbacks',
  4: 'S4 — loose scree, drops and steps',
  5: 'S5 — expert only',
  6: 'S6 — borderline unrideable',
}

// Green through red. Deliberately not the grade-color scale from utils/gradeColor —
// that one maps *steepness*, and a steep fire road is not a technical trail.
const GRADE_COLOR: Record<number, string> = {
  0: '#16a34a',
  1: '#65a30d',
  2: '#ca8a04',
  3: '#ea580c',
  4: '#dc2626',
  5: '#b91c1c',
  6: '#7f1d1d',
}

export function TrailGrade({ difficulty }: { difficulty: number | null | undefined }) {
  if (difficulty == null) return null
  return (
    <span
      title={GRADE_TITLE[difficulty] ?? `mtb:scale ${difficulty}`}
      style={{
        fontSize: '10px',
        fontWeight: 700,
        color: '#fff',
        background: GRADE_COLOR[difficulty] ?? '#6b7280',
        borderRadius: '3px',
        padding: '1px 4px',
        flexShrink: 0,
      }}
    >
      S{difficulty}
    </span>
  )
}
