/**
 * Tests for src/lib/auth.ts
 * All Cookie interactions are mocked via jest.mock('js-cookie').
 */
import Cookies from 'js-cookie'
import { getToken, isAuthenticated, removeToken, setToken } from '@/lib/auth'

jest.mock('js-cookie')

const MockedCookies = Cookies as jest.Mocked<typeof Cookies>

beforeEach(() => {
  jest.clearAllMocks()
})

describe('setToken', () => {
  it('calls Cookies.set with the token key', () => {
    setToken('my-jwt-token')
    expect(MockedCookies.set).toHaveBeenCalledWith(
      'token',
      'my-jwt-token',
      expect.objectContaining({ expires: 1 / 24 }),
    )
  })

  it('sets sameSite to strict', () => {
    setToken('abc')
    expect(MockedCookies.set).toHaveBeenCalledWith(
      'token',
      'abc',
      expect.objectContaining({ sameSite: 'strict' }),
    )
  })

  it('expiry is 1 hour (1/24 of a day)', () => {
    setToken('abc')
    const options = (MockedCookies.set as jest.Mock).mock.calls[0][2]
    expect(options.expires).toBeCloseTo(1 / 24)
  })
})

describe('getToken', () => {
  it('returns the token when cookie is set', () => {
    MockedCookies.get.mockReturnValue('my-jwt-token')
    expect(getToken()).toBe('my-jwt-token')
    expect(MockedCookies.get).toHaveBeenCalledWith('token')
  })

  it('returns undefined when no cookie is set', () => {
    MockedCookies.get.mockReturnValue(undefined)
    expect(getToken()).toBeUndefined()
  })
})

describe('removeToken', () => {
  it('calls Cookies.remove with the token key', () => {
    removeToken()
    expect(MockedCookies.remove).toHaveBeenCalledWith('token')
  })
})

describe('isAuthenticated', () => {
  it('returns true when a token exists', () => {
    MockedCookies.get.mockReturnValue('some-token')
    expect(isAuthenticated()).toBe(true)
  })

  it('returns false when no token is present', () => {
    MockedCookies.get.mockReturnValue(undefined)
    expect(isAuthenticated()).toBe(false)
  })

  it('returns false when token is an empty string', () => {
    MockedCookies.get.mockReturnValue('')
    expect(isAuthenticated()).toBe(false)
  })
})
