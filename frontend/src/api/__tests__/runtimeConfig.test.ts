import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * API_BASE_URL is computed once at module load, so each case here resets
 * the module registry and re-imports fresh with a different
 * `window.__APP_CONFIG__` already in place - the same "load, then read a
 * global" sequence that actually happens in the browser (env-config.js is
 * a <script> tag loaded before src/main.tsx, so window.__APP_CONFIG__ is
 * always set - or the committed empty stub - before client.ts ever runs).
 */
describe('API_BASE_URL runtime-config precedence', () => {
  const originalConfig = window.__APP_CONFIG__

  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    window.__APP_CONFIG__ = originalConfig
  })

  it('prefers window.__APP_CONFIG__.API_BASE_URL when set (the Docker path)', async () => {
    window.__APP_CONFIG__ = { API_BASE_URL: 'https://api.example.com/api/v1' }

    const { API_BASE_URL } = await import('../client')

    expect(API_BASE_URL).toBe('https://api.example.com/api/v1')
  })

  it('falls back to the hardcoded default when __APP_CONFIG__ is the empty stub', async () => {
    window.__APP_CONFIG__ = {}

    const { API_BASE_URL } = await import('../client')

    expect(API_BASE_URL).toBe('http://localhost:8000/api/v1')
  })

  it('falls back to the hardcoded default when __APP_CONFIG__ is entirely absent', async () => {
    delete (window as { __APP_CONFIG__?: unknown }).__APP_CONFIG__

    const { API_BASE_URL } = await import('../client')

    expect(API_BASE_URL).toBe('http://localhost:8000/api/v1')
  })

  it('ignores an __APP_CONFIG__ with a blank API_BASE_URL string', async () => {
    window.__APP_CONFIG__ = { API_BASE_URL: '' }

    const { API_BASE_URL } = await import('../client')

    expect(API_BASE_URL).toBe('http://localhost:8000/api/v1')
  })
})
