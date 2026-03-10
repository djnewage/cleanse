import { makeAuthContext, makeUserDoc, makeDeviceDoc, mockDocSnap, unwrapOnCall } from './helpers'

// Mock firebase-admin before any imports that use it
const mockGet = jest.fn()
const mockDoc = jest.fn(() => ({ get: mockGet }))
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mockCollection: jest.Mock<any> = jest.fn(() => ({ doc: mockDoc }))

jest.mock('firebase-admin', () => {
  const actual = jest.requireActual('firebase-admin')
  return {
    ...actual,
    initializeApp: jest.fn(),
    firestore: Object.assign(
      jest.fn(() => ({
        collection: mockCollection
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

import { canProcessSong } from '../src/index'

const wrapped = unwrapOnCall(canProcessSong)

describe('canProcessSong', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockCollection.mockReturnValue({ doc: mockDoc })
    mockDoc.mockReturnValue({ get: mockGet })
  })

  // --- Validation ---

  it('throws unauthenticated when no auth', async () => {
    await expect(wrapped({}, {})).rejects.toThrow(
      expect.objectContaining({ code: 'unauthenticated' })
    )
  })

  it('throws not-found when user doc missing', async () => {
    mockGet.mockResolvedValue(mockDocSnap(false))
    await expect(wrapped({}, makeAuthContext())).rejects.toThrow(
      expect.objectContaining({ code: 'not-found' })
    )
  })

  // --- Subscriber short-circuit ---

  it('returns unlimited for lifetime subscriber', async () => {
    mockGet.mockResolvedValue(
      mockDocSnap(true, makeUserDoc({ subscription: { status: 'none', lifetime: true, stripeCustomerId: null, stripeSubscriptionId: null, currentPeriodEnd: null } }))
    )

    const result = await wrapped({}, makeAuthContext())
    expect(result).toEqual(
      expect.objectContaining({ canProcess: true, songsRemaining: -1, isSubscribed: true })
    )
  })

  it('returns unlimited for active subscriber', async () => {
    mockGet.mockResolvedValue(
      mockDocSnap(true, makeUserDoc({ subscription: { status: 'active', stripeCustomerId: 'cus_123', stripeSubscriptionId: 'sub_123', currentPeriodEnd: null } }))
    )

    const result = await wrapped({}, makeAuthContext())
    expect(result).toEqual(
      expect.objectContaining({ canProcess: true, songsRemaining: -1, isSubscribed: true })
    )
  })

  it('treats canceled subscription as non-subscriber', async () => {
    const userSnap = mockDocSnap(
      true,
      makeUserDoc({
        songsProcessed: 3,
        subscription: { status: 'canceled', stripeCustomerId: 'cus_1', stripeSubscriptionId: null, currentPeriodEnd: null }
      })
    )
    const deviceSnap = mockDocSnap(true, makeDeviceDoc({ totalSongsProcessed: 2 }))

    const userDocRef = { get: jest.fn().mockResolvedValue(userSnap) }
    const deviceDocRef = { get: jest.fn().mockResolvedValue(deviceSnap) }

    mockCollection.mockImplementation((name: string) => ({
      doc: jest.fn(() => (name === 'users' ? userDocRef : deviceDocRef))
    }))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())
    expect(result).toEqual(
      expect.objectContaining({ canProcess: true, songsRemaining: 3, isSubscribed: false })
    )
  })

  it('treats past_due subscription as non-subscriber', async () => {
    const userSnap = mockDocSnap(
      true,
      makeUserDoc({
        songsProcessed: 3,
        subscription: { status: 'past_due', stripeCustomerId: 'cus_1', stripeSubscriptionId: 'sub_1', currentPeriodEnd: null }
      })
    )
    const deviceSnap = mockDocSnap(true, makeDeviceDoc({ totalSongsProcessed: 4 }))

    const userDocRef = { get: jest.fn().mockResolvedValue(userSnap) }
    const deviceDocRef = { get: jest.fn().mockResolvedValue(deviceSnap) }

    mockCollection.mockImplementation((name: string) => ({
      doc: jest.fn(() => (name === 'users' ? userDocRef : deviceDocRef))
    }))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())
    expect(result).toEqual(
      expect.objectContaining({ canProcess: true, songsRemaining: 1, isSubscribed: false })
    )
  })

  it('falls back to user-level check when data is null (no deviceId)', async () => {
    mockGet.mockResolvedValue(mockDocSnap(true, makeUserDoc({ songsProcessed: 2 })))

    const result = await wrapped(null, makeAuthContext())
    expect(result).toEqual(
      expect.objectContaining({ canProcess: true, songsRemaining: 3, isSubscribed: false })
    )
  })

  // --- Non-subscriber with deviceId ---

  it('returns canProcess: true when device has 0 songs', async () => {
    const userSnap = mockDocSnap(true, makeUserDoc())
    const deviceSnap = mockDocSnap(true, makeDeviceDoc({ totalSongsProcessed: 0 }))

    const userDocRef = { get: jest.fn().mockResolvedValue(userSnap) }
    const deviceDocRef = { get: jest.fn().mockResolvedValue(deviceSnap) }

    mockCollection.mockImplementation((name: string) => ({
      doc: jest.fn(() => (name === 'users' ? userDocRef : deviceDocRef))
    }))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())
    expect(result).toEqual(
      expect.objectContaining({ canProcess: true, songsRemaining: 5, isSubscribed: false })
    )
  })

  it('returns canProcess: false when device has 5 songs', async () => {
    const userSnap = mockDocSnap(true, makeUserDoc())
    const deviceSnap = mockDocSnap(true, makeDeviceDoc({ totalSongsProcessed: 5 }))

    const userDocRef = { get: jest.fn().mockResolvedValue(userSnap) }
    const deviceDocRef = { get: jest.fn().mockResolvedValue(deviceSnap) }

    mockCollection.mockImplementation((name: string) => ({
      doc: jest.fn(() => (name === 'users' ? userDocRef : deviceDocRef))
    }))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())
    expect(result).toEqual(
      expect.objectContaining({ canProcess: false, songsRemaining: 0, isSubscribed: false })
    )
  })

  it('defaults to 0 songs when device doc missing', async () => {
    const userSnap = mockDocSnap(true, makeUserDoc())
    const deviceSnap = mockDocSnap(false)

    const userDocRef = { get: jest.fn().mockResolvedValue(userSnap) }
    const deviceDocRef = { get: jest.fn().mockResolvedValue(deviceSnap) }

    mockCollection.mockImplementation((name: string) => ({
      doc: jest.fn(() => (name === 'users' ? userDocRef : deviceDocRef))
    }))

    const result = await wrapped({ deviceId: 'a'.repeat(64) }, makeAuthContext())
    expect(result).toEqual(
      expect.objectContaining({ canProcess: true, songsRemaining: 5, isSubscribed: false })
    )
  })

  // --- Non-subscriber without deviceId (backwards compat) ---

  it('returns canProcess: true when user has 0 songs (no deviceId)', async () => {
    mockGet.mockResolvedValue(mockDocSnap(true, makeUserDoc({ songsProcessed: 0 })))

    const result = await wrapped({}, makeAuthContext())
    expect(result).toEqual(
      expect.objectContaining({ canProcess: true, songsRemaining: 5, isSubscribed: false })
    )
  })

  it('returns canProcess: false when user has 5 songs (no deviceId)', async () => {
    mockGet.mockResolvedValue(mockDocSnap(true, makeUserDoc({ songsProcessed: 5 })))

    const result = await wrapped({}, makeAuthContext())
    expect(result).toEqual(
      expect.objectContaining({ canProcess: false, songsRemaining: 0, isSubscribed: false })
    )
  })
})
