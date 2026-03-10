import {
  clearFirestore,
  seedDevice,
  getDeviceDoc,
  registerDeviceLogic
} from './helpers'

const DEVICE_ID = 'test-device-' + 'a'.repeat(52)

describe('registerDevice (emulator)', () => {
  beforeEach(async () => {
    await clearFirestore()
  })

  it('creates a new device doc with correct fields', async () => {
    const result = await registerDeviceLogic('uid-1', DEVICE_ID)

    expect(result).toEqual({ success: true, canProcess: true, songsRemaining: 5 })

    const snap = await getDeviceDoc(DEVICE_ID)
    expect(snap.exists).toBe(true)
    const data = snap.data()!
    expect(data.totalSongsProcessed).toBe(0)
    expect(data.linkedUids).toEqual(['uid-1'])
    expect(data.firstSeenAt).toBeDefined()
    expect(data.lastSeenAt).toBeDefined()
  })

  it('adds uid to existing device via arrayUnion', async () => {
    await seedDevice(DEVICE_ID, { linkedUids: ['uid-1'], totalSongsProcessed: 0 })

    await registerDeviceLogic('uid-2', DEVICE_ID)

    const snap = await getDeviceDoc(DEVICE_ID)
    const data = snap.data()!
    expect(data.linkedUids).toContain('uid-1')
    expect(data.linkedUids).toContain('uid-2')
    expect(data.linkedUids).toHaveLength(2)
  })

  it('deduplicates same uid registered twice', async () => {
    await registerDeviceLogic('uid-1', DEVICE_ID)
    await registerDeviceLogic('uid-1', DEVICE_ID)

    const snap = await getDeviceDoc(DEVICE_ID)
    const data = snap.data()!
    expect(data.linkedUids).toEqual(['uid-1'])
  })

  it('handles concurrent registrations — both uids end up in linkedUids', async () => {
    // Register both in parallel
    await Promise.all([
      registerDeviceLogic('uid-a', DEVICE_ID),
      registerDeviceLogic('uid-b', DEVICE_ID)
    ])

    const snap = await getDeviceDoc(DEVICE_ID)
    const data = snap.data()!
    expect(data.linkedUids).toContain('uid-a')
    expect(data.linkedUids).toContain('uid-b')
  })

  it('songsRemaining reflects seeded totalSongsProcessed', async () => {
    await seedDevice(DEVICE_ID, { linkedUids: [], totalSongsProcessed: 3 })

    const result = await registerDeviceLogic('uid-1', DEVICE_ID)

    expect(result).toEqual({ success: true, canProcess: true, songsRemaining: 2 })
  })
})
