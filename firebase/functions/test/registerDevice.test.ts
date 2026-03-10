import { makeAuthContext, makeDeviceDoc, mockDocSnap, mockTransaction, unwrapOnCall } from './helpers'

// Mock firebase-admin before any imports that use it
const tx = mockTransaction()
const mockRunTransaction = jest.fn((fn) => fn(tx))
const mockDoc = jest.fn()
const mockCollection = jest.fn(() => ({ doc: mockDoc }))

jest.mock('firebase-admin', () => {
  const actual = jest.requireActual('firebase-admin')
  return {
    ...actual,
    initializeApp: jest.fn(),
    firestore: Object.assign(
      jest.fn(() => ({
        collection: mockCollection,
        runTransaction: mockRunTransaction
      })),
      actual.firestore
    )
  }
})

// Mock Stripe and params to avoid import errors
jest.mock('stripe', () => jest.fn(() => ({})))
jest.mock('firebase-functions/params', () => ({
  defineSecret: jest.fn((name: string) => ({ value: jest.fn(), name })),
  defineString: jest.fn((name: string) => ({ value: jest.fn(), name }))
}))
jest.mock('firebase-functions', () => {
  const actual = jest.requireActual('firebase-functions')
  return {
    ...actual,
    runWith: jest.fn(() => actual)
  }
})

// Import after mocking
import { registerDevice } from '../src/index'

// Unwrap the onCall handler
const wrapped = unwrapOnCall(registerDevice)

describe('registerDevice', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockCollection.mockReturnValue({ doc: mockDoc })
  })

  // --- Validation ---

  it('throws unauthenticated when no auth context', async () => {
    await expect(wrapped({ deviceId: 'a'.repeat(64) }, {})).rejects.toThrow(
      expect.objectContaining({ code: 'unauthenticated' })
    )
  })

  it('throws invalid-argument when deviceId is missing', async () => {
    await expect(wrapped({}, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'invalid-argument' })
    )
  })

  it('throws invalid-argument when deviceId is not a string', async () => {
    await expect(wrapped({ deviceId: 12345 }, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'invalid-argument' })
    )
  })

  it('throws invalid-argument when deviceId is too short', async () => {
    await expect(wrapped({ deviceId: 'short' }, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'invalid-argument' })
    )
  })

  it('throws invalid-argument when deviceId is exactly 15 chars (boundary)', async () => {
    await expect(wrapped({ deviceId: 'a'.repeat(15) }, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'invalid-argument' })
    )
  })

  it('succeeds when deviceId is exactly 16 chars (boundary)', async () => {
    const deviceRef = { id: 'device-ref' }
    mockDoc.mockReturnValue(deviceRef)
    tx.get.mockResolvedValue(mockDocSnap(false))

    const result = await wrapped({ deviceId: 'a'.repeat(16) }, makeAuthContext())
    expect(result).toEqual({ success: true, canProcess: true, songsRemaining: 5 })
  })

  it('throws invalid-argument when data is null', async () => {
    await expect(wrapped(null, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'invalid-argument' })
    )
  })

  it('throws invalid-argument when data is undefined', async () => {
    await expect(wrapped(undefined, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'invalid-argument' })
    )
  })

  // --- New device ---

  it('creates a new device doc when device does not exist', async () => {
    const deviceRef = { id: 'device-ref' }
    mockDoc.mockReturnValue(deviceRef)
    tx.get.mockResolvedValue(mockDocSnap(false))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())

    expect(tx.set).toHaveBeenCalledWith(
      deviceRef,
      expect.objectContaining({
        totalSongsProcessed: 0,
        linkedUids: ['test-uid']
      })
    )
    expect(result).toEqual({ success: true, canProcess: true, songsRemaining: 5 })
  })

  // --- Existing device ---

  it('updates existing device and returns correct remaining count', async () => {
    const deviceRef = { id: 'device-ref' }
    mockDoc.mockReturnValue(deviceRef)
    tx.get.mockResolvedValue(mockDocSnap(true, makeDeviceDoc({ totalSongsProcessed: 4 })))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())

    expect(tx.update).toHaveBeenCalledWith(
      deviceRef,
      expect.objectContaining({
        linkedUids: expect.anything()
      })
    )
    expect(result).toEqual({ success: true, canProcess: true, songsRemaining: 1 })
  })

  it('returns canProcess: false when device is at the limit', async () => {
    const deviceRef = { id: 'device-ref' }
    mockDoc.mockReturnValue(deviceRef)
    tx.get.mockResolvedValue(mockDocSnap(true, makeDeviceDoc({ totalSongsProcessed: 5 })))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())

    expect(result).toEqual({ success: true, canProcess: false, songsRemaining: 0 })
  })

  it('returns songsRemaining: 0 when device is well over limit', async () => {
    const deviceRef = { id: 'device-ref' }
    mockDoc.mockReturnValue(deviceRef)
    tx.get.mockResolvedValue(mockDocSnap(true, makeDeviceDoc({ totalSongsProcessed: 100 })))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())

    expect(result).toEqual({ success: true, canProcess: false, songsRemaining: 0 })
  })
})
