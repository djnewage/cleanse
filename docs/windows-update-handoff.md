# Handoff: test and release the Windows update fix

Written Sep 17, 2026 on the Mac for the Claude Code session on Tristan's Windows PC.
Read this whole file before touching anything. Everything below was verified on
the Mac side unless it says "unverified on Windows".

## What happened

Tristan had Cleanse 1.20.0 installed on this Windows PC. The in-app updater offered
1.20.1, he clicked **Restart & Update**, and afterwards the app was gone: uninstalled,
not reinstalled. He recovered by downloading `cleanse-1.20.1-x64.exe` from the GitHub
release and running it. Sign-in works on 1.20.1, so the build itself is fine.

GitHub download counts: ~25 Windows downloads of 1.20.0, only 3 of 1.20.1. Most
Windows users are still on 1.20.0 with the broken update path.

## Root causes (all in the app, none in the release feed)

1. **Non-silent install.** `src/main/index.ts` called `autoUpdater.quitAndInstall()`
   with no arguments. electron-updater then launched
   `cleanse-1.20.1-x64.exe --updated --force-run` with no `/S`. Because
   `electron-builder.yml` has `nsis.oneClick: false`, that is the full assisted wizard,
   shown *after* the app quit, and in assisted mode `--force-run` is ignored. If the
   wizard was closed, interrupted, or failed after its uninstall step, nothing was left.
2. **Backend still running in the install dir.** `stopPythonBackend()` in
   `src/main/python-bridge.ts` only sent `kill()` to one PID. The PyInstaller backend
   (`resources\backend\cleanse-backend.exe`) spawns multiprocessing workers and the
   bundled ffmpeg from the same folder; on Windows those outlive the parent and keep
   `$INSTDIR` locked. NSIS retries, then gives up after it has already removed the old
   version. Also, `quitAndInstall` spawns the installer *before* `before-quit` runs.
3. **Disk space.** The installer is 1.9 GB and the installed app is 2.7 GB. During an
   update NSIS parks the old install in `%TEMP%`, extracts a 1.8 GB archive there,
   extracts 2.7 GB again into the install dir, and electron-updater keeps two copies of
   the installer. Peak need is roughly 12 to 15 GB free. Nothing checked.

Ruled out: `latest.yml` naming (matches the uploaded exe), per-user vs per-machine or
GUID drift (installer config unchanged since May), unsigned installer (no
`publisherName` in `app-update.yml`, so signature verification is a no-op).

## What the fix changes (branch `fix/windows-update`, commit a460f66)

- `src/main/index.ts`
  - `install-update` handler now does `await stopPythonBackendAndWait()` and then
    `autoUpdater.quitAndInstall(true, true)` (silent `/S`, force relaunch).
  - `autoUpdater.autoInstallOnAppQuit = false`. The button is the only install path.
  - `download-update` checks free space with `fs/promises.statfs` on the app volume.
    Needs `12 GB` on Windows, `3 GB` on macOS. If short it sends `update-error` with a
    specific message and returns `{ started: false, message }` instead of downloading.
- `src/main/python-bridge.ts`
  - `killBackendTree()`: on Windows `taskkill /PID <pid> /T /F`; elsewhere
    SIGTERM then SIGKILL. `stopPythonBackend()` uses it too.
  - New `stopPythonBackendAndWait(timeoutMs = 8000)`: polls `process.kill(pid, 0)`
    until the PID is gone, escalating halfway through.
- `src/renderer/src/App.tsx` + `components/UpdateModal.tsx`: the modal now shows the
  `update-error` message (free-space refusal included) and re-enables Download.
- `src/preload/index.ts`: `downloadUpdate` typed as `Promise<{ started; message? }>`.
- `electron-builder.yml`: `nsis.allowElevation: false` (the "for all users" radio is
  disabled for non-admins, so an update can never flip to a per-machine install in
  Program Files), `nsis.deleteAppDataOnUninstall: false` (explicit).
- `scripts/release.ps1`: also uploads `*-x64.exe.blockmap` (electron-updater already
  requests it; with it present, updates become deltas instead of a full 1.9 GB
  download), and refuses any asset >= 2,000,000,000 bytes (GitHub rejects 2 GiB).
- `.github/workflows/build-windows.yml`: blockmap added to the upload globs.

`npm run typecheck` passes on the Mac. **Nothing in this list has been run on
Windows yet.** That is this session's job.

## Step 1: get the branch

```powershell
git fetch origin
git checkout fix/windows-update
git log --oneline -3   # expect a460f66 "Fix Windows in-app update..." near the top
npm ci
npm run typecheck
```

## Step 2: build a test release

The Windows release has always been built on this machine, not CI, because this box
has the NVIDIA GPU and `scripts/setup-python.ps1` installs CUDA torch when it sees
`nvidia-smi`. That is why the installer is 1.9 GB. `.env` must be present in the repo
root (it is gitignored) or the renderer bakes in demo Firebase config.

Decide the version with Tristan. The plan is **1.21.0**, shipped together with the
`feat/analytics-foundation` branch. If he wants to test the update fix on its own
first, a `1.20.2` from this branch alone is fine. Either way:

```powershell
# bump package.json "version" first, commit it on the branch
npm run build:win      # builds backend (PyInstaller) + electron-vite + electron-builder
Get-ChildItem dist | Select-Object Name, Length
```

Expect `dist\cleanse-<version>-x64.exe`, `dist\cleanse-<version>-x64.exe.blockmap`,
and `dist\latest.yml`. If the exe is >= 2,000,000,000 bytes the release script will
refuse it; prune the backend bundle (see `backend/cleanse-backend.spec`, the
`_cuda_prune` list) before going further.

## Step 3: the test that matters (unverified on Windows)

Precondition: Cleanse **1.20.1** installed from the GitHub exe (per-user, in
`%LOCALAPPDATA%\Programs\cleanse`). Note that 1.20.1 still has the *old* updater
code, so this first run exercises the old handoff one last time. To test the *new*
handoff you need two builds from this branch (for example 1.20.2-test then 1.20.3), or
test with a locally hosted update feed. Ask Tristan how much of that he wants. At
minimum, do the following with whatever pair of versions you have:

1. Open Task Manager. Confirm `cleanse-backend.exe` is running under Cleanse.
2. In Cleanse: user menu, Check for updates, Download, then **Restart & Update**.
3. Expected with the new code:
   - no installer wizard appears
   - the app closes and relaunches on its own within about 30 seconds
   - `%LOCALAPPDATA%\Programs\cleanse\resources\app.asar` is the new version
   - no orphaned `cleanse-backend.exe` or `ffmpeg-win64-*.exe` in Task Manager
   - `%APPDATA%\cleanse\logs\main.log` contains
     `[AutoUpdater] Stopping backend before install` and
     `Install: isSilent: true, isForceRunAfter: true`
4. Disk-space path: temporarily raise `UPDATE_FREE_SPACE_BYTES` in
   `src/main/index.ts` above the machine's free space, rebuild, click Download, and
   confirm the modal shows "Not enough free space to update..." with the Download
   button still usable. Revert the constant.

Useful diagnostics if anything goes wrong:

```powershell
Get-Content "$env:APPDATA\cleanse\logs\main.log" -Tail 80
Get-ChildItem "$env:LOCALAPPDATA\cleanse-updater" -Recurse | Select-Object FullName, Length
(Get-PSDrive C).Free / 1GB
Get-Process cleanse*, ffmpeg* -ErrorAction SilentlyContinue | Select-Object Name, Id, Path
```

## Step 4: release

The macOS side creates the tag and the GitHub release first (`scripts/release.sh` on
the Mac, run by Tristan). Then on this machine:

```powershell
.\scripts\release.ps1   # builds, then `gh release upload v<version>` with exe + blockmap + latest.yml
```

Needs `gh auth status` to be logged in. After upload, confirm on the release page that
`cleanse-<version>-x64.exe`, `cleanse-<version>-x64.exe.blockmap`, and `latest.yml`
are all attached.

**Release notes must include this line**, because 1.20.0 users still run the old
handoff: "Windows users on 1.20.0: please install this version manually from the
download page. The in-app update in 1.20.0 can fail to reinstall."

## Merge note

`feat/analytics-foundation` (one commit, db266db) also edits the `updateState` block
in `src/renderer/src/App.tsx`. Merging it after this branch conflicts there. It's a
small hand-merge: keep the `error: string | null` field and the `onUpdateError`
listener from this branch, and the `track(...)` calls plus `updateVersionRef` from the
analytics branch. Merge this fix first; it is the one that needs to ship.

## Do not

- Do not switch the release to the CI workflow to "save time". CI has no GPU, so it
  produces a CPU-only build that is not what users have, and it has never been used
  for a real release.
- Do not change `nsis.oneClick` or `perMachine`. Changing install mode between
  versions is a separate way to strand users.
- Do not delete `%LOCALAPPDATA%\cleanse-updater` on Tristan's machine without asking;
  it may hold the evidence of the original failure.

## Longer term (not this session)

Ship CPU-only torch by default and make CUDA an optional download. That takes the
installer from 1.9 GB to well under 1 GB and removes most of the disk-space risk.
Code-signing the Windows installer would also remove SmartScreen friction on manual
installs.
