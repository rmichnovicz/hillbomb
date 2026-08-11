import { useCallback, useRef, useState } from 'react'

/**
 * Drag-to-resize for the mobile bottom sheet.
 *
 * Bound to the handle strip only, not to the sheet body. Dragging anywhere is the
 * tempting version and it is a trap here: the body holds two nested scrollers (the sheet
 * itself and the route list inside it), so a downward drag is ambiguous, and resolving it
 * properly means tracking "is the innermost scroller at the top" through momentum for
 * both of them. The handle is where thumbs go and it has no conflict to resolve.
 *
 * Returns props to spread onto the handle, plus `dragHeightPx` — non-null only while a
 * drag is live, so the caller can drop its CSS height transition for the duration.
 * Animating a property that a pointer is already driving frame by frame just adds lag.
 */

/** Past this, a short flick decides the direction regardless of how far it travelled. */
const FLICK_VELOCITY_PX_PER_MS = 0.5

/** Below this, treat the gesture as a tap and let the click handler have it. */
const TAP_SLOP_PX = 4

interface SheetDragOptions<D extends string> {
  /** Detents in ascending height order. */
  detents: readonly D[]
  current: D
  /** Resolved pixel height of each detent, measured against the live viewport. */
  heightOf: (detent: D) => number
  onSettle: (detent: D) => void
}

export function useSheetDrag<D extends string>({
  detents,
  current,
  heightOf,
  onSettle,
}: SheetDragOptions<D>) {
  const [dragHeightPx, setDragHeightPx] = useState<number | null>(null)
  // A completed drag still ends in a `click` on the handle. Without swallowing it, every
  // drag settles on a detent and then immediately cycles off it — dragging up to `full`
  // lands on `peek`, and a 30px fidget that should spring back opens the sheet instead.
  const swallowNextClick = useRef(false)
  // A ref, not state: the pointermove handler needs these synchronously, and re-rendering
  // per move event to keep them fresh would be pure overhead.
  const gesture = useRef<{
    startY: number
    startHeight: number
    lastY: number
    lastT: number
    velocity: number
    moved: boolean
  } | null>(null)

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    // Ignore secondary buttons; a right-click is not a drag.
    if (e.button !== 0) return
    // Capture keeps the gesture alive once the pointer leaves the handle — which it does
    // immediately, since the handle is 40px tall and the drag spans most of the screen.
    // It throws on a pointerId the browser no longer considers active, and that is
    // survivable: the drag just ends early instead of not starting at all.
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      /* no capture; pointermove still arrives while over the handle */
    }
    gesture.current = {
      startY: e.clientY,
      startHeight: heightOf(current),
      lastY: e.clientY,
      lastT: e.timeStamp,
      velocity: 0,
      moved: false,
    }
  }, [current, heightOf])

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const g = gesture.current
    if (!g) return

    const dy = g.startY - e.clientY  // up is taller
    if (!g.moved && Math.abs(dy) < TAP_SLOP_PX) return
    g.moved = true

    const dt = e.timeStamp - g.lastT
    if (dt > 0) {
      // Up-is-positive, matching dy, so a flick upward reads as positive velocity.
      g.velocity = (g.lastY - e.clientY) / dt
      g.lastY = e.clientY
      g.lastT = e.timeStamp
    }

    const min = heightOf(detents[0])
    const max = heightOf(detents[detents.length - 1])
    setDragHeightPx(Math.max(min, Math.min(max, g.startHeight + dy)))
  }, [detents, heightOf])

  const endDrag = useCallback((e: React.PointerEvent) => {
    const g = gesture.current
    gesture.current = null
    if (!g) return
    try {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId)
      }
    } catch {
      /* capture was never taken, or the pointer is already gone */
    }

    // Never moved: it was a tap. Leave the detent alone and let onClick cycle it.
    if (!g.moved) {
      setDragHeightPx(null)
      return
    }
    swallowNextClick.current = true

    const heights = detents.map(heightOf)
    const released = Math.max(heights[0], Math.min(heights[heights.length - 1], g.startHeight + (g.startY - e.clientY)))
    const index = detents.indexOf(current)

    let target: number
    if (Math.abs(g.velocity) >= FLICK_VELOCITY_PX_PER_MS) {
      // A flick moves exactly one stop, so a hard swipe can't skip the middle detent
      // and leave someone wondering where it went.
      target = g.velocity > 0 ? Math.min(index + 1, detents.length - 1) : Math.max(index - 1, 0)
    } else {
      // Otherwise it rests at whichever detent it was left nearest.
      target = heights.reduce(
        (best, h, i) => (Math.abs(h - released) < Math.abs(heights[best] - released) ? i : best),
        0,
      )
    }

    setDragHeightPx(null)
    if (detents[target] !== current) onSettle(detents[target])
  }, [current, detents, heightOf, onSettle])

  // Capture phase, so it can stop the handle's own bubble-phase onClick. Deliberately
  // not replacing that onClick: it is what makes the handle work from a keyboard, where
  // Enter and Space produce a click and no pointer events at all.
  const onClickCapture = useCallback((e: React.MouseEvent) => {
    if (!swallowNextClick.current) return
    swallowNextClick.current = false
    e.preventDefault()
    e.stopPropagation()
  }, [])

  return {
    dragHeightPx,
    handleProps: {
      onPointerDown,
      onPointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
      onClickCapture,
      // Without this the browser claims vertical drags for scrolling and the handler
      // never sees a coherent gesture.
      style: { touchAction: 'none' as const },
    },
  }
}
