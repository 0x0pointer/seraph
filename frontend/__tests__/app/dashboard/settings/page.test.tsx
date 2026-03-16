/**
 * Tests for src/app/dashboard/settings/page.tsx
 *
 * Covers AccountSkeleton, ProfileDisplay, ProfileEditForm, and SettingsPage loading state.
 */
import { render, screen } from '@testing-library/react'

// ── Mocks ────────────────────────────────────────────────────────────────────

jest.mock('swr', () => ({
  __esModule: true,
  default: jest.fn(),
}))

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/dashboard/settings',
}))

jest.mock('js-cookie', () => ({
  get: jest.fn(() => 'fake-token'),
  remove: jest.fn(),
}))

jest.mock('@/lib/api', () => ({
  api: { get: jest.fn(), put: jest.fn(), patch: jest.fn(), post: jest.fn() },
}))

import useSWR from 'swr'
import SettingsPage from '@/app/dashboard/settings/page'

const mockUser = {
  id: 42,
  username: 'jdoe',
  full_name: 'John Doe',
  email: 'john@example.com',
  role: 'admin',
  org_id: 1,
  team_id: null,
}

const mockTokenData = {
  api_token: 'ts_live_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz',
  created: false,
}

// ── AccountSkeleton (rendered when user is null) ─────────────────────────────

describe('AccountSkeleton', () => {
  it('renders three skeleton placeholder divs when no user data', () => {
    ;(useSWR as jest.Mock).mockReturnValue({
      data: undefined,
      error: null,
      isLoading: true,
      mutate: jest.fn(),
    })

    const { container } = render(<SettingsPage />)
    const pulsingDivs = container.querySelectorAll('.animate-pulse')
    // 3 skeleton rows from AccountSkeleton
    expect(pulsingDivs.length).toBeGreaterThanOrEqual(3)
  })
})

// ── ProfileDisplay (rendered when user exists and not editing) ────────────────

describe('ProfileDisplay', () => {
  beforeEach(() => {
    ;(useSWR as jest.Mock).mockImplementation((key: string) => {
      if (key === '/auth/me') {
        return { data: mockUser, error: null, isLoading: false, mutate: jest.fn() }
      }
      if (key === '/auth/api-token') {
        return { data: mockTokenData, error: null, isLoading: false, mutate: jest.fn() }
      }
      return { data: undefined, error: null, isLoading: false, mutate: jest.fn() }
    })
  })

  it('renders username', () => {
    render(<SettingsPage />)
    expect(screen.getByText('jdoe')).toBeInTheDocument()
  })

  it('renders email', () => {
    render(<SettingsPage />)
    expect(screen.getByText('john@example.com')).toBeInTheDocument()
  })

  it('renders full name', () => {
    render(<SettingsPage />)
    expect(screen.getByText('John Doe')).toBeInTheDocument()
  })

  it('renders role with correct text', () => {
    render(<SettingsPage />)
    expect(screen.getByText('admin')).toBeInTheDocument()
  })

  it('renders user ID', () => {
    render(<SettingsPage />)
    expect(screen.getByText('#42')).toBeInTheDocument()
  })

  it('shows "---" when full_name is null', () => {
    ;(useSWR as jest.Mock).mockImplementation((key: string) => {
      if (key === '/auth/me') {
        return {
          data: { ...mockUser, full_name: null, email: null },
          error: null,
          isLoading: false,
          mutate: jest.fn(),
        }
      }
      if (key === '/auth/api-token') {
        return { data: mockTokenData, error: null, isLoading: false, mutate: jest.fn() }
      }
      return { data: undefined, error: null, isLoading: false, mutate: jest.fn() }
    })

    render(<SettingsPage />)
    const dashes = screen.getAllByText('---')
    expect(dashes.length).toBe(2) // full_name and email
  })
})

// ── ProfileEditForm (rendered when editing) ──────────────────────────────────

describe('ProfileEditForm', () => {
  beforeEach(() => {
    ;(useSWR as jest.Mock).mockImplementation((key: string) => {
      if (key === '/auth/me') {
        return { data: mockUser, error: null, isLoading: false, mutate: jest.fn() }
      }
      if (key === '/auth/api-token') {
        return { data: mockTokenData, error: null, isLoading: false, mutate: jest.fn() }
      }
      return { data: undefined, error: null, isLoading: false, mutate: jest.fn() }
    })
  })

  it('shows edit form with input fields after clicking Edit profile', async () => {
    const { fireEvent } = await import('@testing-library/react')
    render(<SettingsPage />)

    const editBtn = screen.getByText('Edit profile')
    fireEvent.click(editBtn)

    // Should now show input fields for Username, Full name, Email
    const inputs = screen.getAllByRole('textbox')
    expect(inputs.length).toBeGreaterThanOrEqual(2) // username and full_name text inputs

    // Email input is type="email" which is also a textbox role
    const emailInput = screen.getByPlaceholderText('john@example.com')
    expect(emailInput).toBeInTheDocument()
  })

  it('shows Save changes and Cancel buttons in edit mode', async () => {
    const { fireEvent } = await import('@testing-library/react')
    render(<SettingsPage />)

    fireEvent.click(screen.getByText('Edit profile'))

    expect(screen.getByText('Save changes')).toBeInTheDocument()
    expect(screen.getByText('Cancel')).toBeInTheDocument()
  })
})

// ── SettingsPage loading state ───────────────────────────────────────────────

describe('SettingsPage', () => {
  it('renders loading skeleton when user data is not yet available', () => {
    ;(useSWR as jest.Mock).mockReturnValue({
      data: undefined,
      error: null,
      isLoading: true,
      mutate: jest.fn(),
    })

    const { container } = render(<SettingsPage />)
    // Should see Account heading
    expect(screen.getByText('Account')).toBeInTheDocument()
    // Should NOT see Edit profile button when no user
    expect(screen.queryByText('Edit profile')).not.toBeInTheDocument()
    // Should have skeleton placeholders
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThanOrEqual(1)
  })

  it('renders Change Password section', () => {
    ;(useSWR as jest.Mock).mockImplementation((key: string) => {
      if (key === '/auth/me') {
        return { data: mockUser, error: null, isLoading: false, mutate: jest.fn() }
      }
      if (key === '/auth/api-token') {
        return { data: mockTokenData, error: null, isLoading: false, mutate: jest.fn() }
      }
      return { data: undefined, error: null, isLoading: false, mutate: jest.fn() }
    })

    render(<SettingsPage />)
    expect(screen.getByText('Change Password')).toBeInTheDocument()
    expect(screen.getByText('Update password')).toBeInTheDocument()
  })

  it('renders API Token section', () => {
    ;(useSWR as jest.Mock).mockImplementation((key: string) => {
      if (key === '/auth/me') {
        return { data: mockUser, error: null, isLoading: false, mutate: jest.fn() }
      }
      if (key === '/auth/api-token') {
        return { data: mockTokenData, error: null, isLoading: false, mutate: jest.fn() }
      }
      return { data: undefined, error: null, isLoading: false, mutate: jest.fn() }
    })

    render(<SettingsPage />)
    expect(screen.getByText('API Token')).toBeInTheDocument()
    expect(screen.getByText('Regenerate token')).toBeInTheDocument()
    expect(screen.getByText('Usage examples')).toBeInTheDocument()
  })
})
