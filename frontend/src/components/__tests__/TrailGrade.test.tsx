/**
 * TrailGrade renders the route's mtb:scale grade — and, more importantly, renders
 * nothing without one. See the component doc: null means ungraded, not easy.
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TrailGrade } from '../RouteList/TrailGrade'

describe('TrailGrade', () => {
  it('renders the grade as an S-number', () => {
    render(<TrailGrade difficulty={3} />)
    expect(screen.getByText('S3')).toBeTruthy()
  })

  it('renders S0 rather than treating it as absent', () => {
    // 0 is a real grade (smooth doubletrack). A falsiness check here would hide it.
    const { container } = render(<TrailGrade difficulty={0} />)
    expect(screen.getByText('S0')).toBeTruthy()
    expect(container.textContent).toBe('S0')
  })

  it('renders nothing when the route is ungraded', () => {
    // The common case: every paved route, and most trails. A placeholder here would
    // put a difficulty claim on 30-odd road descents.
    const { container } = render(<TrailGrade difficulty={null} />)
    expect(container.textContent).toBe('')
  })

  it('renders nothing when the field is missing entirely', () => {
    const { container } = render(<TrailGrade difficulty={undefined} />)
    expect(container.textContent).toBe('')
  })

  it('describes the grade in a tooltip', () => {
    render(<TrailGrade difficulty={4} />)
    expect(screen.getByTitle(/loose scree/i)).toBeTruthy()
  })
})
