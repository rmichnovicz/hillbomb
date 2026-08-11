/**
 * The Collections tab: curated famous descents, grouped by city.
 *
 * Two modes, one component so App only has to place one element per layout:
 *   - browse: a list of collapsed region folders; expanding one reveals its spot
 *     cards and puts every descent in the region on the map at once
 *   - detail: a header for the opened spot, then the ordinary RouteList of its routes
 *
 * Regions are an accordion — only one open at a time — because the open one *is* what
 * the map is showing. Two open regions would leave "which lines am I looking at?"
 * ambiguous, and would fight over the map viewport.
 *
 * Collection routes are plain `Route`s, so the detail view is just RouteList — the
 * cards, sparklines, hover and selection behavior all come along for free.
 */
import { useState } from 'react'
import { RouteList } from '../RouteList/RouteList'
import type { SortMode } from '../RouteList/RouteList'
import type { CollectionCity, CollectionSpot, CollectionSpotSummary, StartGroup } from '../../types'

// Display names for the discipline tags. Not a contract — anything missing falls back to
// a title-cased tag, so a spot can claim "gravel" or "mtb" and get a sensible chip
// without a frontend change. Mirrors backend/config.py DISCIPLINES.
const DISCIPLINE_LABEL: Record<string, string> = {
  road: 'Road bike',
  skate: 'Skate',
  gravel: 'Gravel',
  mtb: 'MTB',
}

function disciplineLabel(tag: string): string {
  return DISCIPLINE_LABEL[tag] ?? tag.charAt(0).toUpperCase() + tag.slice(1)
}

/** Every discipline tag in use, in DISCIPLINE_LABEL order first, then any unknown ones. */
export function availableDisciplines(cities: CollectionCity[]): string[] {
  const present = new Set(cities.flatMap(c => c.spots.flatMap(s => s.disciplines)))
  const known = Object.keys(DISCIPLINE_LABEL).filter(t => present.has(t))
  const rest = [...present].filter(t => !(t in DISCIPLINE_LABEL)).sort()
  return [...known, ...rest]
}

/** Empty filter means "show all" — an unselected filter bar shouldn't hide anything. */
export function spotMatchesFilter(spot: CollectionSpotSummary, filter: string[]): boolean {
  return filter.length === 0 || spot.disciplines.some(d => filter.includes(d))
}

/**
 * Cities keeping only their matching spots, with empty cities dropped entirely — a
 * region folder that opens onto nothing is worse than no folder.
 */
export function filterCities(cities: CollectionCity[], filter: string[]): CollectionCity[] {
  if (filter.length === 0) return cities
  return cities
    .map(c => ({ ...c, spots: c.spots.filter(s => spotMatchesFilter(s, filter)) }))
    .filter(c => c.spots.length > 0)
}

function DisciplineFilter({ tags, selected, onChange }: {
  tags: string[]
  selected: string[]
  onChange: (next: string[]) => void
}) {
  if (tags.length < 2) return null  // one sport in the whole index — nothing to filter
  const toggle = (tag: string) =>
    onChange(selected.includes(tag) ? selected.filter(t => t !== tag) : [...selected, tag])

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', margin: '0 4px 10px' }}>
      <button
        onClick={() => onChange([])}
        aria-pressed={selected.length === 0}
        style={chipStyle(selected.length === 0)}
      >
        All
      </button>
      {tags.map(tag => (
        <button
          key={tag}
          onClick={() => toggle(tag)}
          aria-pressed={selected.includes(tag)}
          style={chipStyle(selected.includes(tag))}
        >
          {disciplineLabel(tag)}
        </button>
      ))}
    </div>
  )
}

function chipStyle(active: boolean): React.CSSProperties {
  return {
    fontSize: '11px', padding: '3px 9px', borderRadius: '999px',
    border: '1px solid', borderColor: active ? '#3b82f6' : '#d1d5db',
    background: active ? '#eff6ff' : '#fff',
    color: active ? '#1d4ed8' : '#6b7280',
    fontWeight: active ? 600 : 400,
    cursor: 'pointer', fontFamily: 'inherit', lineHeight: 1.6,
  }
}

function formatDistance(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`
}

function FlowBadge({ grade }: { grade: string }) {
  if (!grade) return null
  const color = grade.startsWith('A') ? '#16a34a'
    : grade.startsWith('B') ? '#65a30d'
    : grade.startsWith('C') ? '#ca8a04'
    : grade.startsWith('D') ? '#ea580c'
    : '#dc2626'
  return (
    <span
      title={`Flow grade ${grade}`}
      style={{
        fontSize: '10px', fontWeight: 700, color: '#fff', background: color,
        borderRadius: '3px', padding: '1px 5px', lineHeight: 1.5,
      }}
    >
      {grade}
    </span>
  )
}

function SpotCard({ spot, onSelect, onHover }: {
  spot: CollectionSpotSummary
  onSelect: (slug: string) => void
  onHover: (slug: string | null) => void
}) {
  return (
    <button
      onClick={() => onSelect(spot.slug)}
      onMouseEnter={() => onHover(spot.slug)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(spot.slug)}
      onBlur={() => onHover(null)}
      style={{
        display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
        background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px',
        padding: '10px 12px', marginBottom: '8px', font: 'inherit',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '8px' }}>
        <span style={{ fontSize: '13px', fontWeight: 600, color: '#111827' }}>{spot.name}</span>
        <FlowBadge grade={spot.flow_grade} />
      </div>

      <div style={{ display: 'flex', gap: '10px', margin: '5px 0 6px', fontSize: '11px', color: '#6b7280' }}>
        <span>{formatDistance(spot.length_m)}</span>
        <span>↓ {Math.round(spot.total_descent_m)} m</span>
        <span>{Math.round(spot.top_speed_kmh)} km/h</span>
      </div>

      {/* Blurb only. The notes are the gotchas — closures, legality, surface — and they
          belong with the descent you've committed to looking at, not stacked on twelve
          browse cards where they'd bury the thing you're scanning for. */}
      <p style={{ margin: 0, fontSize: '11px', color: '#9ca3af', lineHeight: 1.45 }}>{spot.blurb}</p>

      <div style={{ marginTop: '6px', fontSize: '10px', color: '#c0c4cc' }}>
        {spot.disciplines.map(disciplineLabel).join(' · ')} · {spot.state}
        {spot.route_count > 1 && ` · ${spot.route_count} lines`}
      </div>
    </button>
  )
}

/** Disclosure chevron; rotates to point down when its folder is open. */
function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"
      style={{
        flexShrink: 0,
        transform: `rotate(${open ? 90 : 0}deg)`,
        transition: 'transform 0.18s ease',
        color: open ? '#1d4ed8' : '#9ca3af',
      }}
    >
      <path d="M3 1 L7 5 L3 9" fill="none" stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/**
 * One region folder: a header row that expands to its spot cards.
 *
 * The collapsed row carries enough of a hook (how many descents, how long the longest
 * one is) to be worth opening — a bare city name gives no reason to click.
 */
function CityFolder({ city, isOpen, isLoading, onToggle, onSelectSpot, onHoverSpot }: {
  city: CollectionCity
  isOpen: boolean
  isLoading: boolean
  onToggle: (city: string) => void
  onSelectSpot: (slug: string) => void
  onHoverSpot: (slug: string | null) => void
}) {
  const count = city.spots.length
  const longest = city.spots.reduce((m, s) => Math.max(m, s.length_m), 0)
  const fastest = city.spots.reduce((m, s) => Math.max(m, s.top_speed_kmh), 0)

  return (
    <section style={{ marginBottom: '6px' }}>
      <button
        onClick={() => onToggle(city.city)}
        aria-expanded={isOpen}
        style={{
          display: 'flex', alignItems: 'center', gap: '9px',
          width: '100%', textAlign: 'left', cursor: 'pointer', font: 'inherit',
          background: isOpen ? '#eff6ff' : '#fff',
          border: '1px solid', borderColor: isOpen ? '#bfdbfe' : '#e5e7eb',
          borderRadius: '8px', padding: '10px 12px', minHeight: '44px',
        }}
      >
        <Chevron open={isOpen} />
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{
            display: 'block', fontSize: '13px', fontWeight: 700,
            color: isOpen ? '#1d4ed8' : '#111827',
          }}>
            {city.city}
          </span>
          <span style={{ display: 'block', fontSize: '11px', color: '#9ca3af', marginTop: '2px' }}>
            {count} descent{count !== 1 ? 's' : ''}
            {longest > 0 && ` · longest ${formatDistance(longest)}`}
            {fastest > 0 && ` · up to ${Math.round(fastest)} km/h`}
          </span>
        </span>
      </button>

      {isOpen && (
        <div style={{ margin: '8px 0 4px 11px', paddingLeft: '11px', borderLeft: '2px solid #bfdbfe' }}>
          {isLoading ? (
            <p style={{ margin: '2px 0 10px', fontSize: '11px', color: '#9ca3af' }}>
              Loading {count} descent{count !== 1 ? 's' : ''}…
            </p>
          ) : (
            <>
              <p style={{ margin: '0 0 8px', fontSize: '10px', color: '#60a5fa', fontWeight: 600 }}>
                All {count} shown on the map
              </p>
              {city.spots.map(spot => (
                <SpotCard key={spot.slug} spot={spot} onSelect={onSelectSpot} onHover={onHoverSpot} />
              ))}
            </>
          )}
        </div>
      )}
    </section>
  )
}

/**
 * The pinned strip of the spot detail view: the way back, and what you're looking at.
 *
 * Two lines, and it is worth keeping it to two. This is `flexShrink: 0` at the top of a
 * panel whose remaining height *is* the scrollable list, so on the mobile sheet every
 * line here comes straight off the route cards — at 91px it was leaving them 73px to
 * share. The third line used to repeat the region that the back button already names,
 * so the state moved up to join it and the line went away.
 */
function SpotHeader({ spot, onBack }: { spot: CollectionSpot; onBack: () => void }) {
  return (
    <div style={{ padding: '8px 12px 9px', borderBottom: '1px solid #e5e7eb', flexShrink: 0, background: '#fff' }}>
      <button
        onClick={onBack}
        style={{
          background: 'none', border: 'none', padding: 0, cursor: 'pointer',
          fontSize: '11px', color: '#3b82f6', fontWeight: 600, marginBottom: '2px',
        }}
      >
        ← {spot.city}, {spot.state}
      </button>
      <div style={{ fontSize: '14px', fontWeight: 700, color: '#111827', lineHeight: 1.25 }}>{spot.name}</div>
    </div>
  )
}

/**
 * Both descriptions, once you've opened a spot: the blurb for why it's worth riding,
 * the notes for what to watch out for.
 *
 * Rendered inside the route list's scroll container rather than in the pinned header,
 * because together they run to ~140px on a phone — Hawk Hill's pair alone is taller
 * than the whole list column on a short browser window, which is how the back button
 * and every route card ended up clipped out of existence.
 *
 * The notes are then clamped, because scrolling past them is the same problem in a
 * politer form: a five-line hazard note at the top of a 165px column means you open a
 * descent and see no descents. Two lines is enough to tell you there is something to
 * read, and the lines you came for stay above the fold.
 */
function SpotDescription({ spot }: { spot: CollectionSpot }) {
  const [notesOpen, setNotesOpen] = useState(false)
  if (!spot.blurb && !spot.notes) return null

  return (
    <div style={{ margin: '0 0 8px' }}>
      {spot.blurb && (
        <p style={{ margin: '0 0 7px', fontSize: '11px', color: '#6b7280', lineHeight: 1.45 }}>
          {spot.blurb}
        </p>
      )}
      {spot.notes && (
        <button
          onClick={() => setNotesOpen(o => !o)}
          aria-expanded={notesOpen}
          style={{
            display: 'block', width: '100%', textAlign: 'left', font: 'inherit', cursor: 'pointer',
            fontSize: '11px', color: '#92400e', lineHeight: 1.45,
            background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '5px', padding: '5px 7px',
          }}
        >
          <span style={notesOpen ? undefined : {
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const,
            overflow: 'hidden',
          }}>
            {spot.notes}
          </span>
          <span style={{ display: 'block', marginTop: '3px', fontWeight: 600, opacity: 0.75 }}>
            {notesOpen ? 'Less' : 'More'}
          </span>
        </button>
      )}
    </div>
  )
}

interface CollectionsPanelProps {
  cities: CollectionCity[]
  /** The open region folder; its descents are what the map is showing. */
  expandedCity: string | null
  activeSpot: CollectionSpot | null
  isLoadingIndex: boolean
  isLoadingCity: boolean
  isLoadingSpot: boolean
  error: string | null
  onToggleCity: (city: string) => void
  onSelectSpot: (slug: string) => void
  /** Hovering a spot card highlights its line on the map. */
  onHoverSpot: (slug: string | null) => void
  onBack: () => void
  // RouteList props, used for the opened spot's routes.
  groups: StartGroup[]
  activeGroupId: string | null
  activeRouteId: string | null
  onSelectGroup: (startNodeId: string) => void
  onSelectRoute: (routeId: string) => void
  /** Selects a route and its group together — how the flat list picks a line. */
  onSelectPath: (routeId: string, startNodeId: string) => void
  onHoverGroup: (id: string | null) => void
  onHoverRoute: (id: string | null) => void
  sortMode: SortMode
  onSortModeChange: (mode: SortMode) => void
  /** Selected discipline tags; empty means show all. */
  disciplineFilter: string[]
  onDisciplineFilterChange: (next: string[]) => void
  fillHeight?: boolean
}

export function CollectionsPanel({
  cities,
  expandedCity,
  activeSpot,
  isLoadingIndex,
  isLoadingCity,
  isLoadingSpot,
  error,
  onToggleCity,
  onSelectSpot,
  onHoverSpot,
  onBack,
  groups,
  activeGroupId,
  activeRouteId,
  onSelectGroup,
  onSelectRoute,
  onSelectPath,
  onHoverGroup,
  onHoverRoute,
  sortMode,
  onSortModeChange,
  disciplineFilter,
  onDisciplineFilterChange,
  fillHeight = true,
}: CollectionsPanelProps) {
  const frame = (children: React.ReactNode) => (
    <div style={{
      display: 'flex', flexDirection: 'column',
      ...(fillHeight ? { height: '100%', overflow: 'hidden' } : {}),
    }}>
      {children}
    </div>
  )

  const message = (text: string, color = '#9ca3af') => (
    <p style={{
      textAlign: 'center', color, fontSize: '13px', marginTop: '24px',
      padding: '0 16px', lineHeight: 1.5,
    }}>
      {text}
    </p>
  )

  if (activeSpot) {
    return frame(
      <>
        <SpotHeader spot={activeSpot} onBack={onBack} />
        <div style={fillHeight ? { flex: 1, minHeight: 0, overflow: 'hidden' } : undefined}>
          <RouteList
            // A spot is already one named descent, so its handful of lines go in a flat
            // list — a folder per starting point was a level of nesting with nothing in
            // it, and it hid two of Hawk Hill's three lines behind a collapsed card.
            flat
            listHeader={<SpotDescription spot={activeSpot} />}
            groups={groups}
            activeGroupId={activeGroupId}
            activeRouteId={activeRouteId}
            onSelectGroup={onSelectGroup}
            onSelectRoute={onSelectRoute}
            onSelectPath={onSelectPath}
            onHoverGroup={onHoverGroup}
            onHoverRoute={onHoverRoute}
            sortMode={sortMode}
            onSortModeChange={onSortModeChange}
            statusMessage={null}
            isSearching={false}
            error={null}
            hasSearched={true}
            fillHeight={fillHeight}
          />
        </div>
      </>
    )
  }

  if (error) return frame(message(error, '#dc2626'))
  if (isLoadingIndex) return frame(message('Loading collections…'))
  if (isLoadingSpot) return frame(message('Loading routes…'))
  if (cities.length === 0) {
    return frame(message(
      'No collections have been built yet. Run `python -m backend.scripts.build_collections` to generate them.'
    ))
  }

  // Chips come from the whole index, not the filtered view, so selecting one doesn't
  // make the others vanish out from under the cursor.
  const tags = availableDisciplines(cities)
  const visibleCities = filterCities(cities, disciplineFilter)

  return frame(
    <div style={{ ...(fillHeight ? { flex: 1, overflowY: 'auto' } : {}), padding: '8px' }}>
      <p style={{ margin: '2px 4px 10px', fontSize: '11px', color: '#9ca3af', lineHeight: 1.45 }}>
        Famous descents. Open a region to see every line on the map.
      </p>
      <DisciplineFilter tags={tags} selected={disciplineFilter} onChange={onDisciplineFilterChange} />
      {visibleCities.length === 0 && message(
        `No curated descents tagged ${disciplineFilter.map(disciplineLabel).join(' or ')} yet.`
      )}
      {visibleCities.map(city => (
        <CityFolder
          key={city.city}
          city={city}
          isOpen={expandedCity === city.city}
          isLoading={expandedCity === city.city && isLoadingCity}
          onToggle={onToggleCity}
          onSelectSpot={onSelectSpot}
          onHoverSpot={onHoverSpot}
        />
      ))}
    </div>
  )
}
