import { mkdir, mkdtemp, rm, symlink, writeFile } from 'fs/promises'
import { tmpdir } from 'os'
import { join, sep } from 'path'
import { afterEach, beforeEach, describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { FileAccessError, createFileAccess, isInside, mediaUrlToPath } from './file-access.ts'

let root: string
let music: string
let previews: string
let stems: string

const file = async (path: string): Promise<string> => {
  await mkdir(join(path, '..'), { recursive: true })
  await writeFile(path, 'audio')
  return path
}

beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), 'cleanse-access-'))
  music = join(root, 'Music')
  previews = join(root, 'tmp', 'cleanse-preview')
  stems = join(root, 'tmp', 'cleanse-separated')
  await mkdir(music, { recursive: true })
  await mkdir(previews, { recursive: true })
  await mkdir(stems, { recursive: true })
})
afterEach(() => rm(root, { recursive: true, force: true }))

describe('the renderer may read what the DJ chose, and what this app made', () => {
  it('a track the DJ added is allowed; the file next to it is not', async () => {
    const access = createFileAccess([previews, stems])
    const chosen = await file(join(music, 'Artist - Title.mp3'))
    const neighbour = await file(join(music, 'Other - Song.mp3'))
    await access.grant([chosen])
    assert.ok(await access.allow(chosen))
    assert.equal(await access.allow(neighbour), null)
  })

  it('knows a granted file by any spelling of its path', async () => {
    const access = createFileAccess([previews])
    const chosen = await file(join(music, 'Artist - Title.mp3'))
    await access.grant([chosen])
    assert.ok(await access.allow(join(music, '.', 'sub', '..', 'Artist - Title.mp3')))
    if (process.platform === 'darwin') {
      assert.ok(await access.allow(chosen.toUpperCase().replace(/^\/PRIVATE/, '/private')))
    }
  })

  it('anything inside the preview and stem folders is allowed without being listed', async () => {
    const access = createFileAccess([previews, stems])
    assert.ok(await access.allow(await file(join(previews, 'Title_preview_1.mp3'))))
    assert.ok(await access.allow(await file(join(stems, 'abc123', 'vocals.wav'))))
  })

  it('the music folder is a root once set, and stops being one when changed', async () => {
    const access = createFileAccess([previews])
    const track = await file(join(music, 'Crate', 'a.mp3'))
    assert.equal(await access.allow(track), null)
    access.setRoot('music', music)
    assert.ok(await access.allow(track))
    const other = join(root, 'Other')
    await mkdir(other)
    access.setRoot('music', other)
    assert.equal(await access.allow(track), null)
    access.setRoot('music', null)
    assert.equal(await access.allow(await file(join(other, 'b.mp3'))), null)
  })

  it('a song queued from the music folder stays readable after the folder is forgotten', async () => {
    const access = createFileAccess([previews])
    const queued = await file(join(music, 'Crate', 'queued.mp3'))
    const notQueued = await file(join(music, 'Crate', 'other.mp3'))
    const outside = await file(join(root, 'elsewhere.mp3'))
    access.setRoot('music', music)
    await access.keep([queued, outside]) // outside is not allowed now, so keep() must not grant it
    access.setRoot('music', null)
    assert.ok(await access.allow(queued))
    assert.equal(await access.allow(notQueued), null)
    assert.equal(await access.allow(outside), null)
  })

  it('a folder that merely shares the prefix is outside', async () => {
    const access = createFileAccess([previews])
    const evil = await file(join(root, 'tmp', 'cleanse-preview-evil', 'x.mp3'))
    assert.ok(evil.startsWith(previews)) // what a prefix check would have accepted
    assert.equal(await access.allow(evil), null)
  })

  it('climbing out of an allowed folder gets nowhere', async () => {
    const access = createFileAccess([previews])
    const secret = await file(join(root, 'secret.txt'))
    assert.equal(await access.allow(join(previews, '..', '..', 'secret.txt')), null)
    assert.equal(await access.allow(secret), null)
  })

  it('a link inside an allowed folder cannot point the app somewhere else', async () => {
    const access = createFileAccess([previews])
    const outside = join(root, 'Documents')
    await file(join(outside, 'taxes.pdf'))
    try {
      await symlink(outside, join(previews, 'link'), 'junction')
    } catch {
      return // this filesystem / account cannot make links; nothing to test
    }
    assert.equal(await access.allow(join(previews, 'link', 'taxes.pdf')), null)
  })

  for (const [what, input] of [
    ['nothing', ''],
    ['a relative path', 'Music/a.mp3'],
    ['a NUL byte', '/Music/a.mp3\0.txt'],
    ['something enormous', '/' + 'a'.repeat(5000)],
    ['not text', 42],
    ['not text', null],
    ['not text', ['/a.mp3']]
  ] as const) {
    it(`refuses ${what}`, async () => {
      const access = createFileAccess([previews])
      assert.equal(await access.allow(input), null)
    })
  }

  it('require() stops the request, and its message carries no path', async () => {
    const access = createFileAccess([previews])
    const secret = await file(join(root, 'Some Artist - Private Demo.mp3'))
    await assert.rejects(access.require(secret, 'a track'), FileAccessError)
    await assert.rejects(access.require(secret, 'a track'), (e: Error) => !/Private Demo|cleanse-access/.test(e.message))
  })

  it('a folder that does not exist yet is still a boundary once it does', async () => {
    const later = join(root, 'tmp', 'not-yet')
    const access = createFileAccess([later])
    assert.ok(await access.allow(join(later, 'x.wav'))) // inside, by name
    assert.equal(await access.allow(join(root, 'tmp', 'not-yet-evil', 'x.wav')), null)
  })

  it('a missing file cannot talk its way inside with ".." after a folder that is not there', async () => {
    const access = createFileAccess([previews])
    assert.equal(await access.allow(previews + sep + ['nope', '..', '..', 'secret.txt'].join(sep)), null)
    assert.ok(await access.allow(previews + sep + ['nope', '..', 'soon.mp3'].join(sep)))
  })

  // The macOS temp folder is a link (/var/folders -> /private/var/folders): the app
  // is told one spelling and the filesystem answers with the other.
  it('a preview folder reached through a link is still the preview folder', async () => {
    const linked = join(root, 'var')
    try {
      await symlink(join(root, 'tmp'), linked, 'junction')
    } catch {
      return
    }
    const access = createFileAccess([join(linked, 'cleanse-preview')])
    assert.ok(await access.allow(await file(join(previews, 'a.mp3')))) // the real spelling
    assert.ok(await access.allow(join(linked, 'cleanse-preview', 'a.mp3'))) // the linked one
    assert.ok(await access.allow(join(linked, 'cleanse-preview', 'not-written-yet.mp3')))
    assert.equal(await access.allow(join(linked, 'cleanse-preview-evil', 'a.mp3')), null)
  })

  it('forgets the oldest grant rather than growing without limit', async () => {
    const access = createFileAccess([], process.platform, 3)
    const files = await Promise.all([1, 2, 3, 4].map((n) => file(join(music, `${n}.mp3`))))
    await access.grant(files)
    assert.equal(access.size(), 3)
    assert.equal(await access.allow(files[0]), null)
    assert.ok(await access.allow(files[3]))
  })
})

describe('isInside — a boundary, not a prefix', () => {
  it('the folder, its contents, and nothing else', () => {
    const r = ['', 'tmp', 'previews'].join(sep)
    assert.equal(isInside(r, r), true)
    assert.equal(isInside(r, r + sep + 'a.mp3'), true)
    assert.equal(isInside(r + sep, r + sep + 'a.mp3'), true)
    assert.equal(isInside(r, r + '-evil' + sep + 'a.mp3'), false)
    assert.equal(isInside(r, ['', 'tmp'].join(sep)), false)
    assert.equal(isInside('', r), false)
  })

  it('macOS-shaped: forward slashes, keys already lower-cased', () => {
    const r = '/private/var/folders/zz/abc123/t/cleanse-preview'
    assert.equal(isInside(r, r + '/title_preview_1.mp3', '/'), true)
    assert.equal(isInside(r, r + '-evil/a.mp3', '/'), false)
    assert.equal(isInside(r, '/var/folders/zz/abc123/t/cleanse-preview/a.mp3', '/'), false) // the unresolved spelling is a different place
    assert.equal(isInside(r, '/users/dj/music/a.mp3', '/'), false)
    // a backslash is part of a NAME on macOS, not a way out of the folder
    assert.equal(isInside(r, r + '\\..\\x.mp3', '/'), false)
  })

  it('windows-shaped: backslashes', () => {
    const r = 'c:\\music'
    assert.equal(isInside(r, 'c:\\music\\crate\\a.mp3', '\\'), true)
    assert.equal(isInside(r, 'c:\\music-evil\\a.mp3', '\\'), false)
  })
})

describe('media:// URLs', () => {
  it('turns the URL the renderer builds back into a path', () => {
    assert.equal(mediaUrlToPath('media://' + encodeURIComponent('C:\\Music\\A & B - Tïtle #1.mp3')), 'C:\\Music\\A & B - Tïtle #1.mp3')
    assert.equal(mediaUrlToPath('media://' + encodeURIComponent('/Users/dj/Music/a.mp3')), '/Users/dj/Music/a.mp3')
  })

  it('accepts the un-encoded form HistoryItem uses', () => {
    assert.equal(mediaUrlToPath('media:///Users/dj/Music/a b.mp3'), '/Users/dj/Music/a b.mp3')
  })

  it('puts back the drive-letter colon Chromium strips, before anything is checked', () => {
    assert.equal(mediaUrlToPath('media://C/Music/a.mp3'), 'C:/Music/a.mp3')
    assert.equal(mediaUrlToPath('media://' + encodeURIComponent('/a/Music/b.mp3')), '/a/Music/b.mp3')
  })

  it('ignores a query or fragment, and refuses what is not a media URL', () => {
    assert.equal(mediaUrlToPath('media://C%3A%5Ca.mp3?t=1#x'), 'C:\\a.mp3')
    assert.equal(mediaUrlToPath('file:///C:/a.mp3'), null)
    assert.equal(mediaUrlToPath('media://%E0%A4%A'), null)
    assert.equal(mediaUrlToPath('media://'), null)
  })
})
