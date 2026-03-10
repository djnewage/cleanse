import {
  clearFirestore,
  seedUser,
  seedDevice,
  canProcessSongLogic,
  incrementUsageLogic
} from './helpers'

const DEVICE_ID = 'test-device-' + 'a'.repeat(52)
const UID = 'test-uid-1'

describe('canProcessSong (emulator)', () => {
  beforeEach(async () => {
    await clearFirestore()
  })

  it('reads real device data correctly', async () => {
    await seedUser(UID, { songsProcessed: 0 })
    await seedDevice(DEVICE_ID, { totalSongsProcessed: 3 })

    const result = await canProcessSongLogic(UID, DEVICE_ID)

    expect(result).toEqual({
      canProcess: true,
      songsProcessed: 3,
      songsRemaining: 2,
      isSubscribed: false
    })
  })

  it('non-existent device defaults to 0 — songsRemaining: 5', async () => {
    await seedUser(UID, { songsProcessed: 0 })

    const result = await canProcessSongLogic(UID, 'nonexistent-device-' + 'b'.repeat(48))

    expect(result).toEqual({
      canProcess: true,
      songsProcessed: 0,
      songsRemaining: 5,
      isSubscribed: false
    })
  })

  it('subscriber bypass with device at limit', async () => {
    await seedUser(UID, { songsProcessed: 100, subscriptionStatus: 'active' })
    await seedDevice(DEVICE_ID, { totalSongsProcessed: 5 })

    const result = await canProcessSongLogic(UID, DEVICE_ID)

    expect(result).toEqual({
      canProcess: true,
      songsProcessed: 100,
      songsRemaining: -1,
      isSubscribed: true
    })
  })

  it('data consistency — increment 3 times, then canProcessSong reflects correct remaining', async () => {
    await seedUser(UID, { songsProcessed: 0 })
    await seedDevice(DEVICE_ID, { totalSongsProcessed: 0 })

    await incrementUsageLogic(UID, DEVICE_ID)
    await incrementUsageLogic(UID, DEVICE_ID)
    await incrementUsageLogic(UID, DEVICE_ID)

    const result = await canProcessSongLogic(UID, DEVICE_ID)

    expect(result).toEqual({
      canProcess: true,
      songsProcessed: 3,
      songsRemaining: 2,
      isSubscribed: false
    })
  })
})
