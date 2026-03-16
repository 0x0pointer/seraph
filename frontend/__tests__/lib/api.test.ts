/**
 * Tests for src/lib/api.ts
 *
 * Global fetch is mocked so no real HTTP calls are made.
 * js-cookie is mocked to control the auth token.
 */
import Cookies from 'js-cookie'
import { api } from '@/lib/api'

jest.mock('js-cookie')
const MockedCookies = Cookies as jest.Mocked<typeof Cookies>

const mockFetch = jest.fn()
global.fetch = mockFetch

// Silence the window.location redirect side-effect in jsdom
const locationSpy = jest.spyOn(window, 'location', 'get')

beforeEach(() => {
  jest.clearAllMocks()
  MockedCookies.get.mockReturnValue('test-token')
})

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockResponse(
  body: unknown,
  status = 200,
  ok = true,
): Response {
  return {
    ok,
    status,
    json: jest.fn().mockResolvedValue(body),
    statusText: 'OK',
  } as unknown as Response
}

// ── GET ───────────────────────────────────────────────────────────────────────

describe('api.get', () => {
  it('makes a GET request to the correct URL', async () => {
    mockFetch.mockResolvedValue(mockResponse({ data: 'ok' }))
    await api.get('/test-path')
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/test-path'),
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) }),
    )
  })

  it('includes Authorization header when token is present', async () => {
    MockedCookies.get.mockReturnValue('my-jwt')
    mockFetch.mockResolvedValue(mockResponse({}))
    await api.get('/me')
    const [, opts] = mockFetch.mock.calls[0]
    expect(opts.headers['Authorization']).toBe('Bearer my-jwt')
  })

  it('omits Authorization header when no token', async () => {
    MockedCookies.get.mockReturnValue(undefined)
    mockFetch.mockResolvedValue(mockResponse({}))
    await api.get('/public')
    const [, opts] = mockFetch.mock.calls[0]
    expect(opts.headers['Authorization']).toBeUndefined()
  })

  it('returns parsed JSON on success', async () => {
    const payload = { id: 1, name: 'Alice' }
    mockFetch.mockResolvedValue(mockResponse(payload))
    const result = await api.get('/users/1')
    expect(result).toEqual(payload)
  })

  it('throws with detail message on non-401 error', async () => {
    mockFetch.mockResolvedValue(
      mockResponse({ detail: 'Not found' }, 404, false),
    )
    await expect(api.get('/missing')).rejects.toThrow('Not found')
  })

  it('throws with statusText when no detail field', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: jest.fn().mockRejectedValue(new Error('no json')),
    } as unknown as Response)
    await expect(api.get('/boom')).rejects.toThrow('Internal Server Error')
  })

  it('returns undefined for 204 No Content', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 204,
      json: jest.fn(),
    } as unknown as Response)
    const result = await api.get('/empty')
    expect(result).toBeUndefined()
  })
})

// ── 401 Handling ──────────────────────────────────────────────────────────────

describe('401 response handling', () => {
  it('removes token and admin_token cookies on 401', async () => {
    mockFetch.mockResolvedValue(mockResponse({ detail: 'Unauthorized' }, 401, false))
    await expect(api.get('/secure')).rejects.toThrow('Session expired')
    // Should have removed auth cookies
    expect(MockedCookies.remove).toHaveBeenCalledWith('token')
    expect(MockedCookies.remove).toHaveBeenCalledWith('admin_token')
  })

  it('throws "Session expired" on 401', async () => {
    mockFetch.mockResolvedValue(mockResponse({}, 401, false))
    await expect(api.get('/secure')).rejects.toThrow('Session expired')
  })
})

// ── POST ──────────────────────────────────────────────────────────────────────

describe('api.post', () => {
  it('sends POST with JSON body', async () => {
    mockFetch.mockResolvedValue(mockResponse({ created: true }, 201))
    await api.post('/items', { name: 'test' })
    const [, opts] = mockFetch.mock.calls[0]
    expect(opts.method).toBe('POST')
    expect(JSON.parse(opts.body)).toEqual({ name: 'test' })
  })
})

// ── PUT ───────────────────────────────────────────────────────────────────────

describe('api.put', () => {
  it('sends PUT with JSON body', async () => {
    mockFetch.mockResolvedValue(mockResponse({ updated: true }))
    await api.put('/items/1', { name: 'updated' })
    const [, opts] = mockFetch.mock.calls[0]
    expect(opts.method).toBe('PUT')
    expect(JSON.parse(opts.body)).toEqual({ name: 'updated' })
  })
})

// ── PATCH ─────────────────────────────────────────────────────────────────────

describe('api.patch', () => {
  it('sends PATCH with body when provided', async () => {
    mockFetch.mockResolvedValue(mockResponse({}))
    await api.patch('/items/1', { active: false })
    const [, opts] = mockFetch.mock.calls[0]
    expect(opts.method).toBe('PATCH')
    expect(JSON.parse(opts.body)).toEqual({ active: false })
  })

  it('sends PATCH without body when omitted', async () => {
    mockFetch.mockResolvedValue(mockResponse({}))
    await api.patch('/toggle/1')
    const [, opts] = mockFetch.mock.calls[0]
    expect(opts.method).toBe('PATCH')
    expect(opts.body).toBeUndefined()
  })
})

// ── DELETE ────────────────────────────────────────────────────────────────────

describe('api.delete', () => {
  it('sends DELETE request', async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 204, json: jest.fn() } as unknown as Response)
    await api.delete('/items/1')
    const [, opts] = mockFetch.mock.calls[0]
    expect(opts.method).toBe('DELETE')
  })
})
