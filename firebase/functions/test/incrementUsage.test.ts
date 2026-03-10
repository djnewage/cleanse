import { makeAuthContext, makeUserDoc, makeDeviceDoc, mockDocSnap, mockTransaction, unwrapOnCall } from './helpers'

// Mock firebase-admin before any imports that use it
const tx = mockTransaction()
const mockRunTransaction = jest.fn((fn) => fn(tx))
const mockDoc = jest.fn()
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mockCollection: jest.Mock<any> = jest.fn(() => ({ doc: mockDoc }))

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

import { incrementUsage } from '../src/index'

const wrapped = unwrapOnCall(incrementUsage)

describe('incrementUsage', () => {
  let userRef: { id: string }
  let deviceRef: { id: string }

  beforeEach(() => {
    jest.clearAllMocks()
    userRef = { id: 'user-ref' }
    deviceRef = { id: 'device-ref' }

    mockCollection.mockImplementation((name: string) => ({
      doc: jest.fn(() => (name === 'users' ? userRef : deviceRef))
    }))
  })

  // --- Validation ---

  it('throws unauthenticated when no auth', async () => {
    await expect(wrapped({}, {})).rejects.toThrow(
      expect.objectContaining({ code: 'unauthenticated' })
    )
  })

  it('throws not-found when user doc missing', async () => {
    tx.get.mockResolvedValue(mockDocSnap(false))
    await expect(wrapped({}, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'not-found' })
    )
  })

  // --- Subscriber ---

  it('increments user count for subscriber without error', async () => {
    tx.get.mockResolvedValue(
      mockDocSnap(
        true,
        makeUserDoc({
          songsProcessed: 100,
          subscription: { status: 'active', stripeCustomerId: 'cus_1', stripeSubscriptionId: 'sub_1', currentPeriodEnd: null }
        })
      )
    )

    const result = await wrapped({}, makeAuthContext())
    expect(result).toEqual({ success: true })
    expect(tx.update).toHaveBeenCalledWith(
      userRef,
      expect.objectContaining({ songsProcessed: expect.anything() })
    )
  })

  it('increments both user and device counts for subscriber with deviceId', async () => {
    tx.get.mockResolvedValueOnce(
      mockDocSnap(
        true,
        makeUserDoc({
          subscription: { status: 'active', stripeCustomerId: 'cus_1', stripeSubscriptionId: 'sub_1', currentPeriodEnd: null }
        })
      )
    )

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())
    expect(result).toEqual({ success: true })
    expect(tx.update).toHaveBeenCalledWith(userRef, expect.objectContaining({ songsProcessed: expect.anything() }))
    expect(tx.update).toHaveBeenCalledWith(deviceRef, expect.objectContaining({ totalSongsProcessed: expect.anything() }))
  })

  // --- Non-subscriber with deviceId ---

  it('increments both counts when device is under limit', async () => {
    tx.get
      .mockResolvedValueOnce(mockDocSnap(true, makeUserDoc({ songsProcessed: 2 })))
      .mockResolvedValueOnce(mockDocSnap(true, makeDeviceDoc({ totalSongsProcessed: 4 })))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())
    expect(result).toEqual({ success: true })
    expect(tx.update).toHaveBeenCalledWith(userRef, expect.objectContaining({ songsProcessed: expect.anything() }))
    expect(tx.update).toHaveBeenCalledWith(deviceRef, expect.objectContaining({ totalSongsProcessed: expect.anything() }))
  })

  it('throws resource-exhausted when device is at limit', async () => {
    tx.get
      .mockResolvedValueOnce(mockDocSnap(true, makeUserDoc({ songsProcessed: 2 })))
      .mockResolvedValueOnce(mockDocSnap(true, makeDeviceDoc({ totalSongsProcessed: 5 })))

    await expect(wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'resource-exhausted' })
    )
  })

  // --- Non-subscriber without deviceId (backwards compat) ---

  it('increments user count when under per-account limit', async () => {
    tx.get.mockResolvedValue(mockDocSnap(true, makeUserDoc({ songsProcessed: 4 })))

    const result = await wrapped({}, makeAuthContext())
    expect(result).toEqual({ success: true })
    expect(tx.update).toHaveBeenCalledWith(userRef, expect.objectContaining({ songsProcessed: expect.anything() }))
    // Should NOT touch device ref
    expect(tx.update).toHaveBeenCalledTimes(1)
  })

  it('throws resource-exhausted when user is at per-account limit', async () => {
    tx.get.mockResolvedValue(mockDocSnap(true, makeUserDoc({ songsProcessed: 5 })))

    await expect(wrapped({}, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'resource-exhausted' })
    )
  })

  // --- Edge cases ---

  it('throws resource-exhausted for canceled subscriber at device limit', async () => {
    tx.get
      .mockResolvedValueOnce(
        mockDocSnap(
          true,
          makeUserDoc({
            songsProcessed: 10,
            subscription: { status: 'canceled', stripeCustomerId: 'cus_1', stripeSubscriptionId: null, currentPeriodEnd: null }
          })
        )
      )
      .mockResolvedValueOnce(mockDocSnap(true, makeDeviceDoc({ totalSongsProcessed: 5 })))

    await expect(wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'resource-exhausted' })
    )
  })

  it('allows lifetime subscriber to bypass device limit', async () => {
    tx.get.mockResolvedValue(
      mockDocSnap(
        true,
        makeUserDoc({
          songsProcessed: 100,
          subscription: { status: 'none', lifetime: true, stripeCustomerId: null, stripeSubscriptionId: null, currentPeriodEnd: null }
        })
      )
    )

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())
    expect(result).toEqual({ success: true })
    expect(tx.update).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ totalSongsProcessed: expect.anything() })
    )
  })

  it('defaults device songs to 0 when device doc missing (allows increment)', async () => {
    tx.get
      .mockResolvedValueOnce(mockDocSnap(true, makeUserDoc({ songsProcessed: 2 })))
      .mockResolvedValueOnce(mockDocSnap(false))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())
    expect(result).toEqual({ success: true })
  })

  it('falls back to user-level limit when data is null (no deviceId)', async () => {
    tx.get.mockResolvedValue(mockDocSnap(true, makeUserDoc({ songsProcessed: 3 })))

    const result = await wrapped(null, makeAuthContext())
    expect(result).toEqual({ success: true })
    // Should only update user, not device
    expect(tx.update).toHaveBeenCalledTimes(1)
  })
})
