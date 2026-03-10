import * as admin from 'firebase-admin'

export interface MockUserData {
  email: string
  createdAt: admin.firestore.Timestamp
  songsProcessed: number
  subscription: {
    status: 'none' | 'active' | 'canceled' | 'past_due'
    lifetime?: boolean
    stripeCustomerId: string | null
    stripeSubscriptionId: string | null
    currentPeriodEnd: admin.firestore.Timestamp | null
  }
}

export interface MockDeviceData {
  totalSongsProcessed: number
  linkedUids: string[]
  firstSeenAt: admin.firestore.Timestamp
  lastSeenAt: admin.firestore.Timestamp
}

export function makeUserDoc(overrides: Partial<MockUserData> = {}): MockUserData {
  const defaults: MockUserData = {
    email: 'test@example.com',
    createdAt: admin.firestore.Timestamp.now(),
    songsProcessed: 0,
    subscription: {
      status: 'none',
      stripeCustomerId: null,
      stripeSubscriptionId: null,
      currentPeriodEnd: null
    }
  }
  const { subscription, ...rest } = overrides
  return {
    ...defaults,
    ...rest,
    subscription: { ...defaults.subscription, ...subscription }
  }
}

export function makeDeviceDoc(overrides: Partial<MockDeviceData> = {}): MockDeviceData {
  return {
    totalSongsProcessed: 0,
    linkedUids: ['test-uid'],
    firstSeenAt: admin.firestore.Timestamp.now(),
    lastSeenAt: admin.firestore.Timestamp.now(),
    ...overrides
  }
}

export function makeAuthContext(uid: string = 'test-uid') {
  return { auth: { uid, token: { email: 'test@example.com' } } }
}

/** Create a mock Firestore document snapshot */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function mockDocSnap(exists: boolean, data?: any) {
  return {
    exists,
    data: () => (exists ? data : undefined),
    ref: { update: jest.fn(), set: jest.fn() }
  }
}

/**
 * Unwrap the internal .run() handler from a firebase-functions onCall function.
 * Centralizes the brittle cast so tests break in one place if the internal API changes.
 */
export function unwrapOnCall<TData = unknown, TResult = unknown>(
  fn: unknown
): (data: TData, context: unknown) => Promise<TResult> {
  const callable = fn as { run?: (data: TData, context: unknown) => Promise<TResult> }
  if (typeof callable?.run !== 'function') {
    throw new Error(
      'unwrapOnCall: could not find .run() on the exported function. ' +
        'firebase-functions internals may have changed.'
    )
  }
  return callable.run.bind(callable)
}

/** Create a mock transaction */
export function mockTransaction() {
  const tx = {
    get: jest.fn(),
    set: jest.fn(),
    update: jest.fn(),
    delete: jest.fn()
  }
  return tx
}
