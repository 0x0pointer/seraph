/**
 * Tests for src/components/dashboard/shared.tsx
 *
 * Covers Sk (skeleton), ChartTip (recharts tooltip), and AdminBanner components.
 */
import { render, screen, fireEvent } from '@testing-library/react'
import { Sk, ChartTip, AdminBanner, OrgOption } from '@/components/dashboard/shared'

// ── Sk (Skeleton) ────────────────────────────────────────────────────────────

describe('Sk', () => {
  it('renders with default height class "h-24"', () => {
    const { container } = render(<Sk />)
    const el = container.firstChild as HTMLElement
    expect(el.className).toContain('h-24')
    expect(el.className).toContain('w-full')
  })

  it('renders with custom height and width', () => {
    const { container } = render(<Sk h="h-10" w="w-48" />)
    const el = container.firstChild as HTMLElement
    expect(el.className).toContain('h-10')
    expect(el.className).toContain('w-48')
    expect(el.className).not.toContain('w-full')
  })
})

// ── ChartTip ─────────────────────────────────────────────────────────────────

describe('ChartTip', () => {
  it('returns null when not active', () => {
    const { container } = render(
      <ChartTip active={false} payload={[{ value: 10, name: 'CPU', color: '#f00' }]} label="Jan" />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('returns null when payload is empty', () => {
    const { container } = render(<ChartTip active={true} payload={[]} label="Jan" />)
    expect(container.firstChild).toBeNull()
  })

  it('renders tooltip with label and payload entries', () => {
    render(
      <ChartTip
        active={true}
        label="March"
        payload={[
          { value: 42, name: 'Users', color: '#0f0' },
          { value: 7, name: 'Sessions', color: '#00f' },
        ]}
      />,
    )
    expect(screen.getByText('March')).toBeInTheDocument()
    expect(screen.getByText('Users: 42')).toBeInTheDocument()
    expect(screen.getByText('Sessions: 7')).toBeInTheDocument()
  })

  it('formats percentage values correctly', () => {
    render(
      <ChartTip
        active={true}
        label="Q1"
        payload={[{ value: 85.678, name: 'CPU %', color: '#f00' }]}
      />,
    )
    expect(screen.getByText('CPU %: 85.7%')).toBeInTheDocument()
  })
})

// ── AdminBanner ──────────────────────────────────────────────────────────────

describe('AdminBanner', () => {
  const orgs: OrgOption[] = [
    { id: 1, name: 'Acme Corp' },
    { id: 2, name: 'Globex' },
  ]

  it('renders "all organizations" when no filterOrgId', () => {
    render(
      <AdminBanner filterOrgId="" adminOrgs={orgs} setFilterOrgId={jest.fn()} />,
    )
    expect(screen.getByText('all organizations')).toBeInTheDocument()
  })

  it('renders org name when filterOrgId matches', () => {
    render(
      <AdminBanner filterOrgId="2" adminOrgs={orgs} setFilterOrgId={jest.fn()} />,
    )
    expect(screen.getAllByText('Globex').length).toBeGreaterThanOrEqual(1)
  })

  it('calls setFilterOrgId on select change', () => {
    const setFilter = jest.fn()
    render(
      <AdminBanner filterOrgId="" adminOrgs={orgs} setFilterOrgId={setFilter} />,
    )
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: '1' } })
    expect(setFilter).toHaveBeenCalledWith('1')
  })

  it('uses custom label prop', () => {
    render(
      <AdminBanner filterOrgId="" adminOrgs={orgs} setFilterOrgId={jest.fn()} label="metrics" />,
    )
    expect(screen.getByText(/showing metrics from/)).toBeInTheDocument()
  })
})
