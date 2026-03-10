import * as admin from 'firebase-admin'

const PROJECT_ID = 'demo-cleanse-test'

let initialized = false

export function getFirestore(): admin.firestore.Firestore {
  if (!initialized) {
    admin.initializeApp({ projectId: PROJECT_ID })
    initialized = true
  }
  return admin.firestore()
}

const db = getFirestore()

/**
 * Clear all Firestore data via the emulator REST API.
 * Must have FIRESTORE_EMULATOR_HOST set.
 */
export async function clearFirestore(): Promise<void> {
  const host = process.env.FIRESTORE_EMULATOR_HOST
  if (!host) {
    throw new Error('FIRESTORE_EMULATOR_HOST not set — are you running the emulator?')
  }
  const res = await fetch(
    `http://${host}/emulator/v1/projects/${PROJECT_ID}/databases/(default)/documents`,
    { method: 'DELETE' }
  )
  if (!res.ok) {
    throw new Error(`Failed to clear Firestore: ${res.status} ${res.statusText}`)
  }
}

export interface SeedUserOptions {
  email?: string
  songsProcessed?: number
  subscriptionStatus?: 'none' | 'active' | 'canceled' | 'past_due'
  lifetime?: boolean
}

export async function seedUser(uid: string, opts: SeedUserOptions = {}): Promise<void> {
  await db
    .collection('users')
    .doc(uid)
    .set({
      email: opts.email ?? 'test@example.com',
      createdAt: admin.firestore.Timestamp.now(),
      songsProcessed: opts.songsProcessed ?? 0,
      subscription: {
        status: opts.subscriptionStatus ?? 'none',
        lifetime: opts.lifetime ?? false,
        stripeCustomerId: null,
        stripeSubscriptionId: null,
        currentPeriodEnd: null
      }
    })
}

export interface SeedDeviceOptions {
  totalSongsProcessed?: number
  linkedUids?: string[]
}

export async function seedDevice(deviceId: string, opts: SeedDeviceOptions = {}): Promise<void> {
  await db
    .collection('devices')
    .doc(deviceId)
    .set({
      totalSongsProcessed: opts.totalSongsProcessed ?? 0,
      linkedUids: opts.linkedUids ?? [],
      firstSeenAt: admin.firestore.Timestamp.now(),
      lastSeenAt: admin.firestore.Timestamp.now()
    })
}

export async function getDeviceDoc(
  deviceId: string
): Promise<admin.firestore.DocumentSnapshot> {
  return db.collection('devices').doc(deviceId).get()
}

export async function getUserDoc(
  uid: string
): Promise<admin.firestore.DocumentSnapshot> {
  return db.collection('users').doc(uid).get()
}

// --- Replicated core logic (avoids importing src/index.ts which calls admin.initializeApp()) ---

const FREE_SONGS_LIMIT = 5

interface DeviceDoc {
  totalSongsProcessed: number
  linkedUids: string[]
  firstSeenAt: admin.firestore.Timestamp
  lastSeenAt: admin.firestore.Timestamp
}

interface UserDoc {
  songsProcessed: number
  subscription: {
    status: string
    lifetime?: boolean
  }
}

export async function registerDeviceLogic(
  uid: string,
  deviceId: string
): Promise<{ success: boolean; canProcess: boolean; songsRemaining: number }> {
  const deviceRef = db.collection('devices').doc(deviceId)

  const result = await db.runTransaction(async (transaction) => {
    const deviceDoc = await transaction.get(deviceRef)

    if (!deviceDoc.exists) {
      transaction.set(deviceRef, {
        totalSongsProcessed: 0,
        linkedUids: [uid],
        firstSeenAt: admin.firestore.Timestamp.now(),
        lastSeenAt: admin.firestore.Timestamp.now()
      })
      return { canProcess: true, songsRemaining: FREE_SONGS_LIMIT }
    }

    const deviceData = deviceDoc.data() as DeviceDoc
    transaction.update(deviceRef, {
      linkedUids: admin.firestore.FieldValue.arrayUnion(uid),
      lastSeenAt: admin.firestore.Timestamp.now()
    })

    const remaining = Math.max(0, FREE_SONGS_LIMIT - deviceData.totalSongsProcessed)
    return {
      canProcess: deviceData.totalSongsProcessed < FREE_SONGS_LIMIT,
      songsRemaining: remaining
    }
  })

  return { success: true, ...result }
}

export async function incrementUsageLogic(
  uid: string,
  deviceId?: string
): Promise<{ success: boolean }> {
  const userRef = db.collection('users').doc(uid)
  const deviceRef = deviceId ? db.collection('devices').doc(deviceId) : null

  await db.runTransaction(async (transaction) => {
    const userDoc = await transaction.get(userRef)

    if (!userDoc.exists) {
      throw new Error('User document not found')
    }

    const userData = userDoc.data() as UserDoc
    const isSubscribed = userData.subscription.lifetime || userData.subscription.status === 'active'

    if (!isSubscribed) {
      if (deviceRef) {
        const deviceDoc = await transaction.get(deviceRef)
        const deviceSongs = deviceDoc.exists
          ? (deviceDoc.data() as DeviceDoc).totalSongsProcessed
          : 0
        if (deviceSongs >= FREE_SONGS_LIMIT) {
          throw new Error('resource-exhausted')
        }
      } else {
        if (userData.songsProcessed >= FREE_SONGS_LIMIT) {
          throw new Error('resource-exhausted')
        }
      }
    }

    transaction.update(userRef, {
      songsProcessed: admin.firestore.FieldValue.increment(1)
    })

    if (deviceRef) {
      transaction.update(deviceRef, {
        totalSongsProcessed: admin.firestore.FieldValue.increment(1),
        lastSeenAt: admin.firestore.Timestamp.now()
      })
    }
  })

  return { success: true }
}

export async function canProcessSongLogic(
  uid: string,
  deviceId?: string
): Promise<{
  canProcess: boolean
  songsProcessed: number
  songsRemaining: number
  isSubscribed: boolean
}> {
  const userDoc = await db.collection('users').doc(uid).get()

  if (!userDoc.exists) {
    throw new Error('User document not found')
  }

  const userData = userDoc.data() as UserDoc
  const isSubscribed = userData.subscription.lifetime || userData.subscription.status === 'active'

  if (isSubscribed) {
    return {
      canProcess: true,
      songsProcessed: userData.songsProcessed,
      songsRemaining: -1,
      isSubscribed: true
    }
  }

  if (deviceId) {
    const deviceDoc = await db.collection('devices').doc(deviceId).get()
    const deviceSongs = deviceDoc.exists
      ? (deviceDoc.data() as DeviceDoc).totalSongsProcessed
      : 0
    const remaining = Math.max(0, FREE_SONGS_LIMIT - deviceSongs)

    return {
      canProcess: deviceSongs < FREE_SONGS_LIMIT,
      songsProcessed: deviceSongs,
      songsRemaining: remaining,
      isSubscribed: false
    }
  }

  return {
    canProcess: userData.songsProcessed < FREE_SONGS_LIMIT,
    songsProcessed: userData.songsProcessed,
    songsRemaining: Math.max(0, FREE_SONGS_LIMIT - userData.songsProcessed),
    isSubscribed: false
  }
}
