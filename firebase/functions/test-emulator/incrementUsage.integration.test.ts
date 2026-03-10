import {
  clearFirestore,
  seedUser,
  seedDevice,
  getUserDoc,
  getDeviceDoc,
  incrementUsageLogic
} from './helpers'

const DEVICE_ID = 'test-device-' + 'a'.repeat(52)
const UID = 'test-uid-1'

describe('incrementUsage (emulator)', () => {
  beforeEach(async () => {
    await clearFirestore()
  })

  it('actually increments user songsProcessed count', async () => {
    await seedUser(UID, { songsProcessed: 2 })
    await seedDevice(DEVICE_ID, { totalSongsProcessed: 2 })

    await incrementUsageLogic(UID, DEVICE_ID)

    const snap = await getUserDoc(UID)
    expect(snap.data()!.songsProcessed).toBe(3)
  })

  it('actually increments device totalSongsProcessed count', async () => {
    await seedUser(UID, { songsProcessed: 2 })
    await seedDevice(DEVICE_ID, { totalSongsProcessed: 2 })

    await incrementUsageLogic(UID, DEVICE_ID)

    const snap = await getDeviceDoc(DEVICE_ID)
    expect(snap.data()!.totalSongsProcessed).toBe(3)
  })

  it('concurrent increments — 3 parallel calls, final count = initial + 3', async () => {
    await seedUser(UID, { songsProcessed: 0 })
    await seedDevice(DEVICE_ID, { totalSongsProcessed: 0 })

    await Promise.all([
      incrementUsageLogic(UID, DEVICE_ID),
      incrementUsageLogic(UID, DEVICE_ID),
      incrementUsageLogic(UID, DEVICE_ID)
    ])

    const userSnap = await getUserDoc(UID)
    const deviceSnap = await getDeviceDoc(DEVICE_ID)
    expect(userSnap.data()!.songsProcessed).toBe(3)
    expect(deviceSnap.data()!.totalSongsProcessed).toBe(3)
  })

  it('limit enforcement at exactly 5 — 4→5 succeeds, 5→6 fails', async () => {
    await seedUser(UID, { songsProcessed: 4 })
    await seedDevice(DEVICE_ID, { totalSongsProcessed: 4 })

    // 4→5 should succeed
    await incrementUsageLogic(UID, DEVICE_ID)
    const deviceSnap = await getDeviceDoc(DEVICE_ID)
    expect(deviceSnap.data()!.totalSongsProcessed).toBe(5)

    // 5→6 should fail
    await expect(incrementUsageLogic(UID, DEVICE_ID)).rejects.toThrow('resource-exhausted')
  })

  it('failed increment leaves both counts unchanged', async () => {
    await seedUser(UID, { songsProcessed: 10 })
    await seedDevice(DEVICE_ID, { totalSongsProcessed: 5 })

    await expect(incrementUsageLogic(UID, DEVICE_ID)).rejects.toThrow('resource-exhausted')

    const userSnap = await getUserDoc(UID)
    const deviceSnap = await getDeviceDoc(DEVICE_ID)
    // User count should be unchanged because the transaction rolled back
    expect(userSnap.data()!.songsProcessed).toBe(10)
    expect(deviceSnap.data()!.totalSongsProcessed).toBe(5)
  })
})
