/**
 * Tests for src/app/register/page.tsx
 *
 * Covers PasswordStrength component behavior and the main RegisterPage form.
 */
import { render, screen, fireEvent } from '@testing-library/react'

// ── Mocks ────────────────────────────────────────────────────────────────────

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/register',
}))

jest.mock('js-cookie', () => ({
  get: jest.fn(() => null),
  set: jest.fn(),
  remove: jest.fn(),
}))

// Mock Turnstile to render a simple button that triggers onSuccess
jest.mock('@marsidev/react-turnstile', () => ({
  Turnstile: ({ onSuccess }: { onSuccess: (token: string) => void }) => (
    <button data-testid="turnstile" onClick={() => onSuccess('test-token')}>
      CAPTCHA
    </button>
  ),
}))

import RegisterPage from '@/app/register/page'

// ── PasswordStrength ─────────────────────────────────────────────────────────

describe('PasswordStrength', () => {
  it('does not render strength indicator when password is empty', () => {
    render(<RegisterPage />)
    // No "Weak", "Fair", "Good", or "Strong" label should be shown
    expect(screen.queryByText('Weak')).not.toBeInTheDocument()
    expect(screen.queryByText('Fair')).not.toBeInTheDocument()
    expect(screen.queryByText('Good')).not.toBeInTheDocument()
    expect(screen.queryByText('Strong')).not.toBeInTheDocument()
  })

  function getPasswordInput() {
    // First password field (the second is confirm)
    return screen.getAllByPlaceholderText('••••••••')[0]
  }

  it('shows "Weak" for a short lowercase-only password', () => {
    render(<RegisterPage />)
    // "abc" has only 1 rule passing (lowercase letter) => "Weak"
    fireEvent.change(getPasswordInput(), { target: { value: 'abc' } })
    expect(screen.getByText('Weak')).toBeInTheDocument()
  })

  it('shows "Fair" for a password meeting 3 rules', () => {
    render(<RegisterPage />)
    // "Abcdefgh" => 8+ chars (pass), uppercase (pass), lowercase (pass), no number, no special => 3 rules => "Fair"
    fireEvent.change(getPasswordInput(), { target: { value: 'Abcdefgh' } })
    expect(screen.getByText('Fair')).toBeInTheDocument()
  })

  it('shows "Good" for a password meeting 4 rules', () => {
    render(<RegisterPage />)
    // "Abcdefg1" => 8+ chars, uppercase, lowercase, number => 4 rules => "Good"
    fireEvent.change(getPasswordInput(), { target: { value: 'Abcdefg1' } })
    expect(screen.getByText('Good')).toBeInTheDocument()
  })

  it('shows "Strong" for a password meeting all 5 rules', () => {
    render(<RegisterPage />)
    // "Abcdefg1!" => all 5 rules pass => "Strong"
    fireEvent.change(getPasswordInput(), { target: { value: 'Abcdefg1!' } })
    expect(screen.getByText('Strong')).toBeInTheDocument()
  })

  it('renders strength bar segments', () => {
    const { container } = render(<RegisterPage />)
    fireEvent.change(getPasswordInput(), { target: { value: 'Abcdefg1!' } })
    // 5 bar segments (one per rule)
    const bars = container.querySelectorAll('.rounded-full.h-1')
    expect(bars.length).toBe(5)
  })

  it('shows correct color (#f87171) for weak password', () => {
    render(<RegisterPage />)
    fireEvent.change(getPasswordInput(), { target: { value: 'ab' } })
    const label = screen.getByText('Weak')
    expect(label).toHaveStyle({ color: '#f87171' })
  })

  it('shows correct color (#5CF097) for strong password', () => {
    render(<RegisterPage />)
    fireEvent.change(getPasswordInput(), { target: { value: 'Abcdefg1!' } })
    const label = screen.getByText('Strong')
    expect(label).toHaveStyle({ color: '#5CF097' })
  })

  it('shows rule checklist items', () => {
    render(<RegisterPage />)
    fireEvent.change(getPasswordInput(), { target: { value: 'a' } })
    expect(screen.getByText('At least 8 characters')).toBeInTheDocument()
    expect(screen.getByText('Uppercase letter')).toBeInTheDocument()
    expect(screen.getByText('Lowercase letter')).toBeInTheDocument()
    expect(screen.getByText('Number')).toBeInTheDocument()
    expect(screen.getByText('Special character (!@#$…)')).toBeInTheDocument()
  })
})

// ── RegisterPage form ────────────────────────────────────────────────────────

describe('RegisterPage', () => {
  it('renders the registration form heading', () => {
    render(<RegisterPage />)
    expect(screen.getByText('Create an account')).toBeInTheDocument()
  })

  it('renders sign-in link', () => {
    render(<RegisterPage />)
    expect(screen.getByText('Sign in')).toBeInTheDocument()
  })

  it('renders all form fields', () => {
    render(<RegisterPage />)
    expect(screen.getByPlaceholderText('Jane Smith')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('jane@example.com')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('janesmith')).toBeInTheDocument()
    // Two password fields with same placeholder
    const pwFields = screen.getAllByPlaceholderText('••••••••')
    expect(pwFields.length).toBe(2)
  })

  it('renders Create account button', () => {
    render(<RegisterPage />)
    expect(screen.getByText('Create account')).toBeInTheDocument()
  })

  it('submit button is disabled when form is incomplete', () => {
    render(<RegisterPage />)
    const btn = screen.getByText('Create account')
    expect(btn).toBeDisabled()
  })

  it('shows password mismatch message when confirm differs', () => {
    render(<RegisterPage />)
    const [pw, confirm] = screen.getAllByPlaceholderText('••••••••')
    fireEvent.change(pw, { target: { value: 'Abcdefg1!' } })
    fireEvent.change(confirm, { target: { value: 'different' } })
    expect(screen.getByText('Passwords do not match')).toBeInTheDocument()
  })

  it('renders the Turnstile CAPTCHA mock', () => {
    render(<RegisterPage />)
    expect(screen.getByTestId('turnstile')).toBeInTheDocument()
  })

  it('renders footer text about viewer access', () => {
    render(<RegisterPage />)
    expect(
      screen.getByText('New accounts have viewer access. Contact an admin to upgrade.'),
    ).toBeInTheDocument()
  })
})
