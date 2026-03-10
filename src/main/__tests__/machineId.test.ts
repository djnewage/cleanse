import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createHash } from 'crypto'

vi.mock('node-machine-id', () => ({
  machineIdSync: vi.fn(() => 'fake-machine-id-1234')
}))

import { machineIdSync } from 'node-machine-id'
import { getHashedMachineId, _resetCache } from '../machineId'

const mockedMachineIdSync = vi.mocked(machineIdSync)

beforeEach(() => {
  _resetCache()
  mockedMachineIdSync.mockClear()
  mockedMachineIdSync.mockReturnValue('fake-machine-id-1234')
})

describe('getHashedMachineId', () => {
  it('returns a 64-char hex string (SHA-256 output)', () => {
    const result = getHashedMachineId()
    expect(result).toMatch(/^[0-9a-f]{64}$/)
  })

  it('produces deterministic output matching manually computed hash', () => {
    const expected = createHash('sha256')
      .update('cleanse-v1-fake-machine-id-1234')
      .digest('hex')
    expect(getHashedMachineId()).toBe(expected)
  })

  it('caches result — machineIdSync called only once across multiple invocations', () => {
    getHashedMachineId()
    getHashedMachineId()
    getHashedMachineId()
    expect(mockedMachineIdSync).toHaveBeenCalledTimes(1)
  })

  it('recomputes after _resetCache()', () => {
    getHashedMachineId()
    _resetCache()
    getHashedMachineId()
    expect(mockedMachineIdSync).toHaveBeenCalledTimes(2)
  })

  it('different raw IDs produce different hashes', () => {
    const hash1 = getHashedMachineId()
    _resetCache()
    mockedMachineIdSync.mockReturnValue('different-machine-id-5678')
    const hash2 = getHashedMachineId()
    expect(hash1).not.toBe(hash2)
  })
})
