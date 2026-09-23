import { mkdir, mkdtemp, rm, symlink, writeFile } from 'fs/promises'
import { tmpdir } from 'os'
import { join } from 'path'
import { afterEach, beforeEach, describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { listMusicFolder, MAX_DEPTH } from './music-folder.ts'

let root: string

const file = async (path: string, bytes = 'audio'): Promise<string> => {
  await mkdir(join(path, '..'), { recursive: true })
  await writeFile(path, bytes)
  return path
}

beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), 'cleanse-music-'))
})
afterEach(() => rm(root, { recursive: true, force: true }))

describe('listMusicFolder', () => {
  it('finds audio at any depth and reports name, size and mtime', async () => {
    await file(join(root, 'A - One.mp3'), '12345')
    await file(join(root, 'Crate', 'Sub', 'B - Two.FLAC'))
    const listing = await listMusicFolder(root)
    const names = listing.files.map((f) => f.name).sort()
    assert.deepEqual(names, ['A - One.mp3', 'B - Two.FLAC'])
    const one = listing.files.find((f) => f.name === 'A - One.mp3')!
    assert.equal(one.size, 5)
    assert.ok(one.mtime > 0)
    assert.equal(one.path, join(root, 'A - One.mp3'))
    assert.equal(listing.capped, false)
  })

  it('ignores non-audio, dotfiles and __MACOSX', async () => {
    await file(join(root, 'cover.jpg'))
    await file(join(root, 'playlist.m3u'))
    await file(join(root, '.DS_Store'))
    await file(join(root, '._Hidden Track.mp3'))
    await file(join(root, '.hidden', 'x.mp3'))
    await file(join(root, '__MACOSX', 'y.mp3'))
    await file(join(root, 'real.mp3'))
    const listing = await listMusicFolder(root)
    assert.deepEqual(listing.files.map((f) => f.name), ['real.mp3'])
  })

  it('does not follow symlinks out of the library', async () => {
    const outside = join(root, '..', 'cleanse-music-outside-' + Date.now())
    await file(join(outside, 'secret.mp3'))
    try {
      try {
        await symlink(outside, join(root, 'link'))
      } catch {
        return // this filesystem cannot make links; nothing to test
      }
      const listing = await listMusicFolder(root)
      assert.deepEqual(listing.files, [])
    } finally {
      await rm(outside, { recursive: true, force: true })
    }
  })

  it('stops at MAX_DEPTH and says so', async () => {
    const deep = Array.from({ length: MAX_DEPTH + 1 }, (_, i) => `d${i}`)
    await file(join(root, ...deep, 'too-deep.mp3'))
    await file(join(root, ...deep.slice(0, MAX_DEPTH - 1), 'just-fits.mp3'))
    const listing = await listMusicFolder(root)
    assert.deepEqual(listing.files.map((f) => f.name), ['just-fits.mp3'])
    assert.equal(listing.depthLimited, true)
  })

  it('caps the listing and says the list is not the whole folder', async () => {
    for (let i = 0; i < 5; i++) await file(join(root, `track-${i}.mp3`))
    const listing = await listMusicFolder(root, { maxEntries: 3 })
    assert.equal(listing.files.length, 3)
    assert.equal(listing.capped, true)
  })

  it('an unreadable or missing folder yields an empty listing, not an error', async () => {
    const listing = await listMusicFolder(join(root, 'nope'))
    assert.deepEqual(listing.files, [])
  })
})
