import * as Sentry from '@sentry/react'
import pkg from '../../../package.json'
import { useReducer, useEffect, useCallback, useRef, useState, useMemo } from 'react'
import type {
  BatchAppState,
  BatchAppAction,
  CensorType,
  ExportFormat,
  SongEntry,
  CensorWord,
  TranscribedWord,
  AppSettings,
  MusicFolderListing,
  ImportSource
} from './types'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import {
  track,
  errorKind,
  logSongsImported,
  logManualCensorAdded,
  setAnalyticsDevice,
  type PaywallReason
} from './lib/analytics'
import { useQueueProcessor } from './hooks/useQueueProcessor'
import FileUpload from './components/FileUpload'
import MusicFolder from './components/MusicFolder'
import QueueList from './components/QueueList'
import BatchControls from './components/BatchControls'
import SongDetailPanel from './components/SongDetailPanel'
import HistoryList from './components/HistoryList'
import AuthScreen from './components/AuthScreen'
import UserMenu from './components/UserMenu'
import UsageIndicator from './components/UsageIndicator'
import PaywallModal from './components/PaywallModal'
import FeedbackModal from './components/FeedbackModal'
import UpdateModal from './components/UpdateModal'
import TurboToggle from './components/TurboToggle'
import DualPassToggle from './components/DualPassToggle'
import HelpModal from './components/HelpModal'
import ThemeToggle from './components/ThemeToggle'
import CustomWordList from './components/CustomWordList'
import { ThemeProvider } from './contexts/ThemeContext'

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

function normalizeWord(word: string): string {
  return word.toLowerCase().replace(/[^\w']/g, '')
}

function fuzzyMatch(word: string, target: string): boolean {
  const w = normalizeWord(word)
  const t = normalizeWord(target)
  if (!w || !t) return false
  // Exact or startsWith match (damn -> damned, dammit)
  if (w === t || w.startsWith(t) || t.startsWith(w)) return true
  // Levenshtein-like: allow 1 char difference for words >= 4 chars
  if (w.length >= 4 && t.length >= 4 && Math.abs(w.length - t.length) <= 2) {
    let matches = 0
    const shorter = w.length <= t.length ? w : t
    const longer = w.length > t.length ? w : t
    for (let i = 0; i < shorter.length; i++) {
      if (longer.includes(shorter[i])) matches++
    }
    return matches / longer.length >= 0.8
  }
  return false
}

function resolveExportExt(sourceName: string, format: ExportFormat): string {
  if (format !== 'source') return format
  return sourceName.split('.').pop()?.toLowerCase() || 'mp3'
}

function applyCustomProfanity(words: TranscribedWord[], customWords: string[]): TranscribedWord[] {
  if (customWords.length === 0) return words
  return words.map((w) => {
    if (w.is_profanity) return w
    for (const custom of customWords) {
      if (fuzzyMatch(w.word, custom)) {
        return { ...w, is_profanity: true, detection_source: 'custom' as const }
      }
    }
    return w
  })
}

const initialState: BatchAppState = {
  backendReady: false,
  globalDefaultCensorType: 'mute',
  songs: [],
  currentlyProcessingId: null,
  processingQueue: [],
  expandedSongId: null,
  history: [],
  isExportingAll: false,
  exportProgress: null,
  turboEnabled: false,
  dualPassEnabled: true,
  deviceInfo: null,
  crossfadeMs: 30,
  paddingMs: 100,
  customProfanityWords: []
}

function reducer(state: BatchAppState, action: BatchAppAction): BatchAppState {
  switch (action.type) {
    case 'SET_BACKEND_STATUS':
      return { ...state, backendReady: action.ready }

    case 'ADD_SONGS': {
      // One-click adding from the library makes double-adds easy; a song is
      // in the queue once, whichever way it arrived. (handleFilesSelected
      // filters first so it can say so; this is the invariant's home.)
      const present = new Set(state.songs.map((s) => s.filePath))
      const unique = action.songs.filter((s) => {
        if (present.has(s.filePath)) return false
        present.add(s.filePath)
        return true
      })
      if (unique.length === 0) return state
      const newSongs: SongEntry[] = unique.map((s) => ({
        id: generateId(),
        filePath: s.filePath,
        fileName: s.fileName,
        status: 'pending',
        words: [],
        duration: 0,
        language: '',
        vocalsPath: null,
        accompanimentPath: null,
        separationProgress: null,
        transcriptionProgress: null,
        censoredFilePath: null,
        previewFilePath: null,
        previewStale: false,
        isGeneratingPreview: false,
        defaultCensorType: state.globalDefaultCensorType,
        userReviewed: false,
        errorMessage: null,
        metadata: null,
        lyrics: null
      }))
      return {
        ...state,
        songs: [...state.songs, ...newSongs]
        // Don't add to processingQueue yet - wait for metadata to be fetched
      }
    }

    case 'REMOVE_SONG':
      return {
        ...state,
        songs: state.songs.filter((s) => s.id !== action.id),
        processingQueue: state.processingQueue.filter((id) => id !== action.id),
        expandedSongId: state.expandedSongId === action.id ? null : state.expandedSongId
      }

    case 'CLEAR_ALL_SONGS':
      return {
        ...state,
        songs: [],
        processingQueue: [],
        currentlyProcessingId: null,
        expandedSongId: null
      }

    case 'SET_EXPANDED_SONG':
      return { ...state, expandedSongId: action.id }

    case 'START_PROCESSING':
      return { ...state, currentlyProcessingId: action.id }

    case 'SET_SONG_METADATA': {
      const song = state.songs.find((s) => s.id === action.id)
      const shouldAddToQueue = song &&
                              song.status === 'pending' &&
                              !state.processingQueue.includes(action.id)

      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, metadata: action.metadata } : s
        ),
        processingQueue: shouldAddToQueue
          ? [...state.processingQueue, action.id]
          : state.processingQueue
      }
    }

    case 'SET_SONG_LYRICS':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, lyrics: action.lyrics } : s
        )
      }

    case 'START_FETCHING_LYRICS':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, status: 'fetching_lyrics' } : s
        )
      }

    case 'START_TRANSCRIPTION':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, status: 'transcribing', errorMessage: null, transcriptionProgress: null } : s
        )
      }

    case 'TRANSCRIPTION_PROGRESS':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, transcriptionProgress: action.progress } : s
        )
      }

    case 'TRANSCRIPTION_COMPLETE':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id
            ? { ...s, words: applyCustomProfanity(action.words, state.customProfanityWords), duration: action.duration, language: action.language, transcriptionProgress: null }
            : s
        )
      }

    case 'START_VOCALS_TRANSCRIPTION':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, status: 'transcribing_vocals' } : s
        )
      }

    case 'START_SEPARATING':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, status: 'separating', separationProgress: null } : s
        )
      }

    case 'SEPARATION_PROGRESS':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, separationProgress: action.progress } : s
        )
      }

    case 'SEPARATION_COMPLETE':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id
            ? {
                ...s,
                vocalsPath: action.vocalsPath,
                accompanimentPath: action.accompanimentPath,
                separationProgress: null
              }
            : s
        )
      }

    case 'SET_SONG_READY':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, status: 'ready' } : s
        )
      }

    case 'SET_SONG_ERROR':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, status: 'error', errorMessage: action.message } : s
        )
      }

    case 'PROCESSING_COMPLETE':
      return {
        ...state,
        currentlyProcessingId: null,
        processingQueue: state.processingQueue.filter((id) => id !== action.id)
      }

    case 'ADD_MANUAL_WORD':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.songId
            ? {
                ...s,
                status: s.status === 'completed' ? 'ready' : s.status,
                words: [...s.words, action.word].sort((a, b) => a.start - b.start),
                censoredFilePath: null,
                previewStale: true
              }
            : s
        )
      }

    case 'REMOVE_WORD':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.songId
            ? {
                ...s,
                status: s.status === 'completed' ? 'ready' : s.status,
                words: s.words.filter((_, i) => i !== action.wordIndex),
                censoredFilePath: null,
                previewStale: true
              }
            : s
        )
      }

    case 'TOGGLE_PROFANITY':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.songId
            ? {
                ...s,
                status: s.status === 'completed' ? 'ready' : s.status,
                words: s.words.map((w, i) =>
                  i === action.wordIndex ? { ...w, is_profanity: !w.is_profanity } : w
                ),
                censoredFilePath: null,
                previewStale: true
              }
            : s
        )
      }

    case 'SET_WORD_CENSOR_TYPE':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.songId
            ? {
                ...s,
                status: s.status === 'completed' ? 'ready' : s.status,
                words: s.words.map((w, i) =>
                  i === action.wordIndex ? { ...w, censor_type: action.censorType } : w
                ),
                censoredFilePath: null,
                previewStale: true
              }
            : s
        )
      }

    case 'RESET_ALL_WORD_CENSOR_TYPES':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.songId
            ? {
                ...s,
                status: s.status === 'completed' ? 'ready' : s.status,
                words: s.words.map((w) => ({ ...w, censor_type: undefined })),
                censoredFilePath: null,
                previewStale: true
              }
            : s
        )
      }

    case 'SET_SONG_CENSOR_TYPE':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.songId
            ? { ...s, status: s.status === 'completed' ? 'ready' : s.status, defaultCensorType: action.censorType, censoredFilePath: null, previewStale: true }
            : s
        )
      }

    case 'START_PREVIEW_GENERATION':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, isGeneratingPreview: true } : s
        )
      }

    case 'PREVIEW_GENERATED':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id
            // errorMessage is cleared because a successful render resolves any
            // previous preview failure. The error banner is no longer gated on
            // previewFilePath being null (a stale preview stays mounted now), so
            // a leftover message would otherwise sit next to a working preview.
            ? {
                ...s,
                previewFilePath: action.previewPath,
                previewStale: false,
                isGeneratingPreview: false,
                errorMessage: null
              }
            : s
        )
      }

    case 'PREVIEW_GENERATION_FAILED':
      // Clear staleness too: previewStale means "a replacement is coming", and
      // after a failure none is. Left set, the player's "updating..." status
      // would run forever with nothing behind it, and the regen guard would
      // keep treating the song as unfinished work.
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id
            ? { ...s, isGeneratingPreview: false, previewStale: false, errorMessage: action.error }
            : s
        )
      }

    case 'CLEAR_PREVIEW':
      // Marks the shown preview out of date WITHOUT unmounting it: the player
      // keeps playing it (and the playhead survives) until the regenerated file
      // replaces it.
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, previewStale: true, isGeneratingPreview: false } : s
        )
      }

    case 'DROP_PREVIEW':
      // Genuinely removes the preview — used when nothing is left to censor, so
      // there is no replacement coming and the player must fall back to the
      // original rather than keep playing a stale censored file.
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id
            ? { ...s, previewFilePath: null, previewStale: false, isGeneratingPreview: false }
            : s
        )
      }

    case 'SET_GLOBAL_CENSOR_TYPE':
      return {
        ...state,
        globalDefaultCensorType: action.censorType,
        songs: state.songs.map((s) => {
          if (s.status === 'exporting' || s.status === 'completed') return s
          if (s.status === 'ready') {
            return { ...s, defaultCensorType: action.censorType, censoredFilePath: null, previewStale: true }
          }
          return { ...s, defaultCensorType: action.censorType }
        })
      }

    case 'MARK_SONG_REVIEWED':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, userReviewed: true } : s
        )
      }

    case 'START_EXPORT':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, status: 'exporting' } : s
        )
      }

    case 'EXPORT_COMPLETE':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, status: 'completed', censoredFilePath: action.outputPath } : s
        )
      }

    case 'START_EXPORT_ALL':
      return {
        ...state,
        isExportingAll: true,
        exportProgress: { completed: 0, total: action.total }
      }

    case 'EXPORT_ALL_PROGRESS':
      return {
        ...state,
        exportProgress: state.exportProgress
          ? { ...state.exportProgress, completed: action.completed }
          : null
      }

    case 'EXPORT_ALL_COMPLETE':
      return {
        ...state,
        isExportingAll: false,
        exportProgress: null
      }

    case 'RETRY_SONG': {
      const song = state.songs.find((s) => s.id === action.id)
      if (!song || song.status !== 'error') return state
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id
            ? { ...s, status: 'pending', errorMessage: null, words: [], vocalsPath: null, accompanimentPath: null, transcriptionProgress: null, separationProgress: null, lyrics: null }
            : s
        ),
        processingQueue: [...state.processingQueue, action.id]
      }
    }

    case 'CANCEL_SONG': {
      const song = state.songs.find((s) => s.id === action.id)
      if (!song) return state
      const processingStatuses = ['fetching_lyrics', 'separating', 'transcribing', 'transcribing_vocals']
      if (!processingStatuses.includes(song.status as string)) return state
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id
            ? { ...s, status: 'pending' as const, errorMessage: null, words: [], vocalsPath: null, accompanimentPath: null, transcriptionProgress: null, separationProgress: null, lyrics: null }
            : s
        ),
        currentlyProcessingId: null,
        processingQueue: state.processingQueue.filter((id) => id !== action.id)
      }
    }

    case 'SET_HISTORY':
      return { ...state, history: action.history }

    case 'ADD_HISTORY_ENTRY':
      return { ...state, history: [action.entry, ...state.history] }

    case 'DELETE_HISTORY_ENTRY':
      return { ...state, history: state.history.filter((e) => e.id !== action.id) }

    case 'SET_DEVICE_INFO':
      return { ...state, deviceInfo: action.deviceInfo }

    case 'SET_TURBO_ENABLED':
      return { ...state, turboEnabled: action.enabled }

    case 'SET_DUAL_PASS_ENABLED':
      return { ...state, dualPassEnabled: action.enabled }

    case 'SET_CROSSFADE_MS':
      return { ...state, crossfadeMs: action.ms }

    case 'SET_PADDING_MS':
      return { ...state, paddingMs: action.ms }

    case 'ADD_CUSTOM_WORD': {
      const word = action.word.toLowerCase().trim()
      if (state.customProfanityWords.includes(word)) return state
      const newCustomWords = [...state.customProfanityWords, word]
      return {
        ...state,
        customProfanityWords: newCustomWords,
        songs: state.songs.map((s) => ({
          ...s,
          words: applyCustomProfanity(s.words, newCustomWords),
          previewStale: true
        }))
      }
    }

    case 'REMOVE_CUSTOM_WORD': {
      const newCustomWords = state.customProfanityWords.filter((w) => w !== action.word)
      return {
        ...state,
        customProfanityWords: newCustomWords,
        songs: state.songs.map((s) => ({
          ...s,
          words: s.words.map((w) =>
            w.detection_source === 'custom' && fuzzyMatch(w.word, action.word)
              ? { ...w, is_profanity: false, detection_source: undefined }
              : w
          ),
          previewStale: true
        }))
      }
    }

    case 'SET_CUSTOM_WORDS':
      return { ...state, customProfanityWords: action.words }

    default:
      return state
  }
}

function MainApp(): React.JSX.Element {
  const [state, dispatch] = useReducer(reducer, initialState)
  const exportingRef = useRef(false)
  const generationRequestRef = useRef<number>(0)
  const [showPaywall, setShowPaywall] = useState(false)
  const [showFeedback, setShowFeedback] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [showCustomWords, setShowCustomWords] = useState(false)
  const [updateState, setUpdateState] = useState<{
    show: boolean
    version: string
    releaseNotes: string
    downloadProgress: number | null
    downloaded: boolean
    error: string | null
  }>({ show: false, version: '', releaseNotes: '', downloadProgress: null, downloaded: false, error: null })

  const {
    isAuthenticated,
    isLoading: authLoading,
    checkCanProcess,
    recordUsage,
    recordSongsImported,
    recordSongsReady,
    songsRemaining
  } = useAuth()

  // Every paywall open goes through here so the reason is recorded. The
  // paywall -> checkout ratio is the free-to-paid funnel's key step.
  const openPaywall = useCallback(
    (reason: PaywallReason) => {
      track('paywall_shown', { reason, songs_remaining: songsRemaining })
      track('screen_view', { screen_name: 'paywall' })
      setShowPaywall(true)
    },
    [songsRemaining]
  )

  // Model warmup state
  const [modelStatus, setModelStatus] = useState<'waiting' | 'downloading' | 'loading' | 'ready'>('waiting')

  // Machine-local folders (music library, export destination). Main owns
  // the file; this is a mirror refreshed whenever a dialog changes one.
  const [settings, setSettings] = useState<AppSettings>({ musicFolder: null, exportFolder: null })
  const [library, setLibrary] = useState<MusicFolderListing | null>(null)
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [libraryOpen, setLibraryOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem('cleanse-library-open') !== 'false'
    } catch {
      return true
    }
  })
  const [importNotice, setImportNotice] = useState<string | null>(null)
  const noticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // The latest songs, for callbacks that must not re-create on every change.
  const songsRef = useRef(state.songs)
  songsRef.current = state.songs

  const showImportNotice = useCallback((message: string) => {
    setImportNotice(message)
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current)
    noticeTimerRef.current = setTimeout(() => setImportNotice(null), 4000)
  }, [])

  const loadLibrary = useCallback(async () => {
    setLibraryLoading(true)
    try {
      setLibrary(await window.electronAPI.listMusicFolder())
    } catch (err) {
      Sentry.captureException(err)
      setLibrary(null)
    } finally {
      setLibraryLoading(false)
    }
  }, [])

  useEffect(() => {
    window.electronAPI.getSettings().then(setSettings).catch(() => {})
  }, [])

  useEffect(() => {
    if (settings.musicFolder) void loadLibrary()
    else setLibrary(null)
  }, [settings.musicFolder, loadLibrary])

  useEffect(() => {
    try {
      localStorage.setItem('cleanse-library-open', String(libraryOpen))
    } catch {
      /* per-viewer convenience only */
    }
  }, [libraryOpen])

  const handleChooseMusicFolder = useCallback(async () => {
    const dir = await window.electronAPI.selectMusicFolder()
    if (!dir) return
    setSettings((prev) => ({ ...prev, musicFolder: dir }))
    setLibraryOpen(true)
    track('music_folder_set')
  }, [])

  const handleForgetMusicFolder = useCallback(async () => {
    await window.electronAPI.clearMusicFolder()
    setSettings((prev) => ({ ...prev, musicFolder: null }))
  }, [])

  const handleChangeExportFolder = useCallback(async () => {
    const dir = await window.electronAPI.selectOutputDirectory()
    if (dir) setSettings((prev) => ({ ...prev, exportFolder: dir }))
  }, [])

  const handleForgetExportFolder = useCallback(async () => {
    await window.electronAPI.clearExportFolder()
    setSettings((prev) => ({ ...prev, exportFolder: null }))
  }, [])
  const [modelDownloadProgress, setModelDownloadProgress] = useState(0)
  const [modelDownloadMessage, setModelDownloadMessage] = useState('')
  const [exportFormat, setExportFormat] = useState<ExportFormat>(() => {
    try {
      const saved = localStorage.getItem('cleanse.exportFormat')
      if (saved === 'source' || saved === 'mp3' || saved === 'wav' || saved === 'flac') {
        return saved
      }
    } catch { /* ignore */ }
    return 'source'
  })

  useEffect(() => {
    try {
      localStorage.setItem('cleanse.exportFormat', exportFormat)
    } catch { /* ignore quota errors */ }
  }, [exportFormat])

  const handleSetExportFormat = useCallback((format: ExportFormat) => {
    track('export_format_changed', { format })
    setExportFormat(format)
  }, [])

  // Track the expanded song's preview identity AND staleness as one value so
  // effects that depend on regeneration re-fire when CLEAR_PREVIEW marks the
  // shown preview stale (the path itself no longer changes at that moment —
  // the old file stays mounted so playback survives the edit).
  const expandedSongPreviewPath = state.expandedSongId
    ? (() => {
        const s = state.songs.find((x) => x.id === state.expandedSongId)
        return s ? `${s.previewFilePath ?? ''}|${s.previewStale}` : null
      })()
    : null

  // Memoized signature of expanded song's censored words
  const expandedSongWordsSignature = useMemo(() => {
    if (!state.expandedSongId) return null
    const song = state.songs.find((s) => s.id === state.expandedSongId)
    if (!song) return null

    // Create signature from profane words + their censor types
    return song.words
      .filter((w) => w.is_profanity)
      .map((w) => `${w.word}:${w.start}:${w.end}:${w.censor_type ?? song.defaultCensorType}`)
      .join('|')
  }, [state.expandedSongId, state.songs])

  // Use the queue processor hook
  const { retrySong, cancelSong } = useQueueProcessor({
    songs: state.songs,
    currentlyProcessingId: state.currentlyProcessingId,
    processingQueue: state.processingQueue,
    turboEnabled: state.turboEnabled,
    dualPassEnabled: state.dualPassEnabled,
    dispatch,
    onSongReady: recordSongsReady
  })

  // Load custom profanity words from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem('cleanse-custom-words')
      if (saved) {
        const words = JSON.parse(saved) as string[]
        if (Array.isArray(words)) dispatch({ type: 'SET_CUSTOM_WORDS', words })
      }
    } catch { /* ignore parse errors */ }
  }, [])

  // Save custom profanity words to localStorage
  useEffect(() => {
    localStorage.setItem('cleanse-custom-words', JSON.stringify(state.customProfanityWords))
  }, [state.customProfanityWords])

  // Listen for backend status updates
  useEffect(() => {
    const unsubscribe = window.electronAPI.onBackendStatus((status) => {
      dispatch({ type: 'SET_BACKEND_STATUS', ready: status.ready })
    })

    window.electronAPI.getBackendStatus().then((status) => {
      dispatch({ type: 'SET_BACKEND_STATUS', ready: status.ready })
    })

    return unsubscribe
  }, [])

  // Warmup model after backend is ready (downloads on first launch, instant thereafter)
  useEffect(() => {
    if (!state.backendReady) return
    if (modelStatus !== 'waiting') return

    setModelStatus('downloading')
    setModelDownloadMessage('Checking audio engine...')
    const warmupStartedAt = performance.now()
    track('model_download_started')

    const unsubProgress = window.electronAPI.onModelDownloadProgress((progress) => {
      setModelDownloadProgress(progress.progress)
      setModelDownloadMessage(progress.message)
      if (progress.step === 'downloading') {
        setModelStatus('downloading')
      } else if (progress.step === 'loading') {
        setModelStatus('loading')
      } else if (progress.step === 'complete') {
        setModelStatus('ready')
      }
    })

    window.electronAPI.warmupModel()
      .then(() => {
        setModelStatus('ready')
        track('model_download_completed', { elapsed_ms: Math.round(performance.now() - warmupStartedAt) })
      })
      .catch((err) => {
        console.error('Model warmup failed:', err)
        track('model_download_failed', { elapsed_ms: Math.round(performance.now() - warmupStartedAt) })
        setModelStatus('ready') // Allow usage even if warmup fails
      })

    return unsubProgress
  }, [state.backendReady, modelStatus])

  // Listen for device info (main process sends this after backend is ready)
  useEffect(() => {
    const unsubscribe = window.electronAPI.onDeviceInfo((info) => {
      dispatch({ type: 'SET_DEVICE_INFO', deviceInfo: info })
      setAnalyticsDevice(info)
    })

    // Fetch only if backend is already ready (handles late-mount / hot-reload)
    if (state.backendReady) {
      window.electronAPI.getDeviceInfo().then((info) => {
        dispatch({ type: 'SET_DEVICE_INFO', deviceInfo: info })
        setAnalyticsDevice(info)
      }).catch(() => {
        // Will get it from the event
      })
    }

    return unsubscribe
  }, [state.backendReady])

  // Listen for auto-update events
  const updateVersionRef = useRef('')
  useEffect(() => {
    const unsubAvailable = window.electronAPI.onUpdateAvailable((info) => {
      let notes = ''
      if (typeof info.releaseNotes === 'string') {
        notes = info.releaseNotes
      } else if (Array.isArray(info.releaseNotes)) {
        notes = info.releaseNotes.map((n) => `${n.version}: ${n.note}`).join('\n')
      }
      // Signature of a git commit trailer (e.g. "Co-Authored-By: ..."). When a
      // GitHub release body is empty, electron-updater's Atom feed backfills the
      // update info with raw commit messages — if we see trailer syntax, the
      // content is commit-message fallback, not real release notes.
      const looksLikeCommitFallback = /^(Co-Authored-By|Signed-off-by):/im.test(notes)
      // Decode entities first so escaped HTML (e.g. &lt;strong&gt;) becomes real
      // tags that the strip pass can then remove. electron-updater may return HTML.
      notes = notes
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/<[^>]*>/g, '')
        .trim()
      if (looksLikeCommitFallback) {
        notes = 'Bug fixes and improvements.'
      }
      updateVersionRef.current = info.version
      track('update_available', { version: info.version })
      setUpdateState({
        show: true,
        version: info.version,
        releaseNotes: notes,
        downloadProgress: null,
        downloaded: false,
        error: null
      })
    })

    // Download failures (including the free-space refusal from the main
    // process) land here so the modal can show the reason and re-enable the
    // Download button instead of sitting on a dead progress bar.
    const unsubError = window.electronAPI.onUpdateError((message) => {
      setUpdateState((prev) => (prev.show ? { ...prev, error: message, downloadProgress: null } : prev))
    })

    const unsubProgress = window.electronAPI.onDownloadProgress((progress) => {
      setUpdateState((prev) => ({ ...prev, downloadProgress: progress.percent }))
    })

    const unsubDownloaded = window.electronAPI.onUpdateDownloaded(() => {
      setUpdateState((prev) => ({ ...prev, downloaded: true, downloadProgress: 100 }))
      track('update_downloaded', { version: updateVersionRef.current })
    })

    return () => {
      unsubAvailable()
      unsubProgress()
      unsubDownloaded()
      unsubError()
    }
  }, [])

  // Load history on mount
  useEffect(() => {
    window.electronAPI.getHistory().then((history) => {
      dispatch({ type: 'SET_HISTORY', history })
    })
  }, [])

  // Extract metadata for new songs that don't have it yet
  useEffect(() => {
    const songsNeedingMetadata = state.songs.filter((s) => s.metadata === null)
    for (const song of songsNeedingMetadata) {
      window.electronAPI.getAudioMetadata(song.filePath).then((metadata) => {
        dispatch({ type: 'SET_SONG_METADATA', id: song.id, metadata })
      }).catch(() => {
        // Metadata extraction is best-effort
      })
    }
  }, [state.songs.length]) // Only run when songs are added/removed

  // Handle file selection
  const handleFilesSelected = useCallback(
    (files: Array<{ path: string; name: string }>, source: ImportSource) => {
      const queued = new Set(songsRef.current.map((s) => s.filePath))
      const fresh = files.filter((f) => !queued.has(f.path))
      const skipped = files.length - fresh.length
      if (skipped > 0) {
        showImportNotice(
          fresh.length === 0
            ? skipped === 1
              ? 'That song is already in the queue'
              : `All ${skipped} are already in the queue`
            : `${skipped} already in the queue — added ${fresh.length}`
        )
      }
      if (fresh.length === 0) return
      dispatch({
        type: 'ADD_SONGS',
        songs: fresh.map((f) => ({ filePath: f.path, fileName: f.name }))
      })
      logSongsImported(fresh.length, source)
      recordSongsImported(fresh.length)
    },
    [recordSongsImported, showImportNotice]
  )

  // Toggle expanded song
  const handleToggleExpand = useCallback(async (id: string) => {
    const song = state.songs.find((s) => s.id === id)
    if (state.expandedSongId !== id) track('screen_view', { screen_name: 'song_panel' })

    if (state.expandedSongId === id) {
      // Closing - cancel any in-flight preview generation
      generationRequestRef.current = Date.now() // Invalidate current request
      dispatch({ type: 'SET_EXPANDED_SONG', id: null })
    } else {
      // Opening
      dispatch({ type: 'SET_EXPANDED_SONG', id })

      // Generate preview if song is ready and no preview exists and has profanity
      if (song && song.status === 'ready' && (!song.previewFilePath || song.previewStale) && !song.isGeneratingPreview) {
        const profaneWords = song.words.filter((w) => w.is_profanity)
        if (profaneWords.length > 0) {
          dispatch({ type: 'START_PREVIEW_GENERATION', id })

          try {
            const censorWords: CensorWord[] = profaneWords.map((w) => ({
              word: w.word,
              start: w.start,
              end: w.end,
              censor_type: w.censor_type ?? song.defaultCensorType,
              detection_source: w.detection_source
            }))

            const previewPath = await window.electronAPI.previewAudio({
              filePath: song.filePath,
              censorWords,
              vocalsPath: song.vocalsPath ?? undefined,
              accompanimentPath: song.accompanimentPath ?? undefined,
              crossfadeMs: state.crossfadeMs,
              paddingBeforeMs: Math.round(state.paddingMs * 1.5),
              paddingAfterMs: state.paddingMs,
              outputFormat: exportFormat === 'source' ? undefined : exportFormat
            })

            dispatch({ type: 'PREVIEW_GENERATED', id, previewPath })
          } catch (error) {
            Sentry.captureException(error)
            const message = error instanceof Error ? error.message : String(error)
            dispatch({ type: 'PREVIEW_GENERATION_FAILED', id, error: message })
          }
        }
      }
    }
  }, [state.expandedSongId, state.songs, state.crossfadeMs, state.paddingMs, exportFormat])

  // Clear preview when crossfade, padding, or export format changes so it regenerates.
  // Bumping the request ref invalidates any in-flight regen so its dispatch is skipped,
  // preventing a stale preview from committing with old settings.
  useEffect(() => {
    if (!state.expandedSongId) return
    generationRequestRef.current = Date.now()
    dispatch({ type: 'CLEAR_PREVIEW', id: state.expandedSongId })
  }, [state.crossfadeMs, state.paddingMs, exportFormat])

  // Auto-regenerate preview when words change while panel is open
  useEffect(() => {
    // Only regenerate if panel is open and song is ready
    if (!state.expandedSongId) return

    const song = state.songs.find((s) => s.id === state.expandedSongId)
    if (!song || song.status !== 'ready') return

    // Don't regenerate while the shown preview still matches the current words
    // and settings. Staleness of any in-flight regen is handled by
    // generationRequestRef — checking isGeneratingPreview here would drop the
    // latest settings change when a regen is still running.
    if (song.previewFilePath && !song.previewStale) return

    // Nothing left to censor: no regeneration is coming, so drop the stale
    // preview instead of leaving a censored file playing for a clean edit.
    const profaneWords = song.words.filter((w) => w.is_profanity)
    if (profaneWords.length === 0) {
      if (song.previewFilePath) dispatch({ type: 'DROP_PREVIEW', id: song.id })
      return
    }

    // Debounce: Set timeout to regenerate preview after 500ms
    const timeoutId = setTimeout(async () => {
      // Generate unique request ID to track staleness
      const requestId = Date.now()
      generationRequestRef.current = requestId

      dispatch({ type: 'START_PREVIEW_GENERATION', id: song.id })

      try {
        const censorWords: CensorWord[] = profaneWords.map((w) => ({
          word: w.word,
          start: w.start,
          end: w.end,
          censor_type: w.censor_type ?? song.defaultCensorType,
          detection_source: w.detection_source
        }))

        const previewPath = await window.electronAPI.previewAudio({
          filePath: song.filePath,
          censorWords,
          vocalsPath: song.vocalsPath ?? undefined,
          accompanimentPath: song.accompanimentPath ?? undefined,
          crossfadeMs: state.crossfadeMs,
          paddingBeforeMs: Math.round(state.paddingMs * 1.5),
          paddingAfterMs: state.paddingMs,
          outputFormat: exportFormat === 'source' ? undefined : exportFormat
        })

        // Only update if this request is still current
        if (generationRequestRef.current === requestId) {
          dispatch({ type: 'PREVIEW_GENERATED', id: song.id, previewPath })
        }
      } catch (error) {
        Sentry.captureException(error)
        // Only update error if this request is still current
        if (generationRequestRef.current === requestId) {
          const message = error instanceof Error ? error.message : String(error)
          dispatch({ type: 'PREVIEW_GENERATION_FAILED', id: song.id, error: message })
        }
      }
    }, 500)

    return () => clearTimeout(timeoutId)
  }, [state.expandedSongId, expandedSongWordsSignature, state.crossfadeMs, state.paddingMs, exportFormat, expandedSongPreviewPath])

  // Remove song from queue
  const handleRemoveSong = useCallback((id: string) => {
    dispatch({ type: 'REMOVE_SONG', id })
  }, [])

  // Clear all songs
  const handleClearAll = useCallback(() => {
    dispatch({ type: 'CLEAR_ALL_SONGS' })
  }, [])

  // Set global censor type
  const handleSetGlobalCensorType = useCallback((censorType: CensorType) => {
    dispatch({ type: 'SET_GLOBAL_CENSOR_TYPE', censorType })
    track('censor_style_changed', { style: censorType, scope: 'global' })
  }, [])

  // Toggle profanity for a word
  const handleToggleProfanity = useCallback((songId: string, wordIndex: number) => {
    // A word switched OFF is the model's false positive as judged by the user.
    const word = state.songs.find((s) => s.id === songId)?.words[wordIndex]
    if (word?.is_profanity) track('word_toggled_off', { detection_source: word.detection_source ?? 'unknown' })
    dispatch({ type: 'TOGGLE_PROFANITY', songId, wordIndex })
    dispatch({ type: 'CLEAR_PREVIEW', id: songId })
  }, [state.songs])

  // Add a manual censor word
  const handleAddManualWord = useCallback((songId: string, word: TranscribedWord) => {
    dispatch({ type: 'ADD_MANUAL_WORD', songId, word })
    dispatch({ type: 'CLEAR_PREVIEW', id: songId })
    logManualCensorAdded()
  }, [])

  // Remove a word (manual censors)
  const handleRemoveWord = useCallback((songId: string, wordIndex: number) => {
    const word = state.songs.find((s) => s.id === songId)?.words[wordIndex]
    track('word_removed', { detection_source: word?.detection_source ?? 'unknown' })
    dispatch({ type: 'REMOVE_WORD', songId, wordIndex })
    dispatch({ type: 'CLEAR_PREVIEW', id: songId })
  }, [state.songs])

  // Set censor type for a word (undefined = reset to default)
  const handleSetWordCensorType = useCallback(
    (songId: string, wordIndex: number, censorType: CensorType | undefined) => {
      dispatch({ type: 'SET_WORD_CENSOR_TYPE', songId, wordIndex, censorType })
      dispatch({ type: 'CLEAR_PREVIEW', id: songId })
      track('censor_style_changed', { style: censorType ?? 'default', scope: 'word' })
    },
    []
  )

  // Reset all per-word censor type overrides for a song
  const handleResetAllWordCensorTypes = useCallback((songId: string) => {
    dispatch({ type: 'RESET_ALL_WORD_CENSOR_TYPES', songId })
    dispatch({ type: 'CLEAR_PREVIEW', id: songId })
    track('censor_style_changed', { style: 'default', scope: 'word_reset' })
  }, [])

  // Set censor type for a song
  const handleSetSongCensorType = useCallback((songId: string, censorType: CensorType) => {
    dispatch({ type: 'SET_SONG_CENSOR_TYPE', songId, censorType })
    dispatch({ type: 'CLEAR_PREVIEW', id: songId })
    track('censor_style_changed', { style: censorType, scope: 'song' })
  }, [])

  // Mark song as reviewed
  const handleMarkReviewed = useCallback((songId: string) => {
    dispatch({ type: 'MARK_SONG_REVIEWED', id: songId })
  }, [])

  // Close expanded panel
  const handleCloseExpanded = useCallback(() => {
    dispatch({ type: 'SET_EXPANDED_SONG', id: null })
  }, [])

  // Delete history entry
  const handleDeleteHistoryEntry = useCallback((id: string) => {
    window.electronAPI.deleteHistoryEntry(id).then(() => {
      dispatch({ type: 'DELETE_HISTORY_ENTRY', id })
    })
  }, [])

  // Export a single song
  const handleExportSong = useCallback(async (songId: string) => {
    const song = state.songs.find((s) => s.id === songId)
    if (!song || (song.status !== 'ready' && song.status !== 'completed')) return

    const usageInfo = await checkCanProcess()
    if (!usageInfo.canProcess) {
      openPaywall('limit_reached')
      return
    }

    const profaneWords = song.words.filter((w) => w.is_profanity)
    if (profaneWords.length === 0) return

    const censorWords: CensorWord[] = profaneWords.map((w) => ({
      word: w.word,
      start: w.start,
      end: w.end,
      censor_type: w.censor_type ?? song.defaultCensorType,
      detection_source: w.detection_source
    }))

    const baseName = song.fileName
    const sourceExt = baseName.split('.').pop() || 'mp3'
    const targetExt = resolveExportExt(baseName, exportFormat)
    const cleanName = baseName.replace(`.${sourceExt}`, `_clean.${targetExt}`)

    const outputPath = await window.electronAPI.selectOutputPath(cleanName)
    if (!outputPath) return

    dispatch({ type: 'START_EXPORT', id: song.id })
    track('export_started', { count: 1, format: exportFormat, mode: 'single', truncated_by_quota: false })

    try {
      const result = await window.electronAPI.censorAudio(
        song.filePath,
        censorWords,
        outputPath,
        song.vocalsPath ?? undefined,
        song.accompanimentPath ?? undefined,
        state.crossfadeMs,
        state.paddingMs,
        state.paddingMs,
        exportFormat === 'source' ? undefined : exportFormat
      )
      dispatch({ type: 'EXPORT_COMPLETE', id: song.id, outputPath: result.output_path })
      track('export_completed', { count: 1, failed: 0, format: exportFormat, mode: 'single' })

      await recordUsage()

      const profanityCount = profaneWords.length
      await window.electronAPI.addHistoryEntry({
        originalFileName: song.fileName,
        originalFilePath: song.filePath,
        censoredFilePath: result.output_path,
        dateCreated: Date.now(),
        wordCount: song.words.length,
        profanityCount,
        duration: song.duration,
        language: song.language
      })
    } catch (err) {
      console.error('Export failed:', err)
      const message = err instanceof Error ? err.message : String(err)
      track('song_failed', { stage: 'export', error_kind: errorKind(message) })
      track('export_completed', { count: 0, failed: 1, format: exportFormat, mode: 'single' })
      dispatch({ type: 'SET_SONG_ERROR', id: song.id, message })
    }
  }, [state.songs, state.crossfadeMs, state.paddingMs, exportFormat, checkCanProcess, recordUsage, openPaywall])

  // Export all ready songs with paywall check
  const handleExportAll = useCallback(async () => {
    if (exportingRef.current) return

    // Check if user can process
    const usageInfo = await checkCanProcess()
    if (!usageInfo.canProcess) {
      openPaywall('limit_reached')
      return
    }

    exportingRef.current = true

    const allExportable = state.songs.filter(
      (s) => (s.status === 'ready' || s.status === 'completed') && s.words.some((w) => w.is_profanity)
    )

    if (allExportable.length === 0) {
      exportingRef.current = false
      return
    }

    // Export as many as the remaining quota covers, then show the paywall once
    // they're written. Previously a batch larger than the quota exported nothing
    // at all, so a free user with 2 remaining and 5 ready songs got a paywall
    // instead of the 2 exports they were entitled to.
    const quotaLimited = !usageInfo.isSubscribed && allExportable.length > usageInfo.songsRemaining
    const exportableSongs = quotaLimited
      ? allExportable.slice(0, Math.max(0, usageInfo.songsRemaining))
      : allExportable

    if (exportableSongs.length === 0) {
      openPaywall('limit_reached')
      exportingRef.current = false
      return
    }

    // For a single song, show Save dialog so user can edit the filename.
    // For multiple songs, show folder picker.
    let outputDir: string | null = null
    let singleOutputPath: string | null = null

    if (exportableSongs.length === 1) {
      const song = exportableSongs[0]
      const baseName = song.fileName
      const sourceExt = baseName.split('.').pop() || 'mp3'
      const targetExt = resolveExportExt(baseName, exportFormat)
      const cleanName = baseName.replace(`.${sourceExt}`, `_clean.${targetExt}`)
      singleOutputPath = await window.electronAPI.selectOutputPath(cleanName)
      if (!singleOutputPath) {
        exportingRef.current = false
        return
      }
    } else {
      // A remembered export folder skips the picker; the folder line under
      // the batch controls is where the DJ changes or forgets it.
      outputDir = settings.exportFolder ?? (await window.electronAPI.selectOutputDirectory())
      if (!outputDir) {
        exportingRef.current = false
        return
      }
      if (outputDir !== settings.exportFolder) setSettings((prev) => ({ ...prev, exportFolder: outputDir }))
    }

    dispatch({ type: 'START_EXPORT_ALL', total: exportableSongs.length })
    track('export_started', {
      count: exportableSongs.length,
      format: exportFormat,
      mode: 'batch',
      truncated_by_quota: quotaLimited
    })

    let completed = 0
    let written = 0

    for (const song of exportableSongs) {
      dispatch({ type: 'START_EXPORT', id: song.id })

      try {
        const profaneWords = song.words.filter((w) => w.is_profanity)
        const censorWords: CensorWord[] = profaneWords.map((w) => ({
          word: w.word,
          start: w.start,
          end: w.end,
          censor_type: w.censor_type ?? song.defaultCensorType,
          detection_source: w.detection_source
        }))

        const baseName = song.fileName
        const sourceExt = baseName.split('.').pop() || 'mp3'
        const targetExt = resolveExportExt(baseName, exportFormat)
        const cleanName = baseName.replace(`.${sourceExt}`, `_clean.${targetExt}`)
        const outputPath = singleOutputPath ?? `${outputDir}/${cleanName}`

        const result = await window.electronAPI.censorAudio(
          song.filePath,
          censorWords,
          outputPath,
          song.vocalsPath ?? undefined,
          song.accompanimentPath ?? undefined,
          state.crossfadeMs,
          state.paddingMs,
          state.paddingMs,
          exportFormat === 'source' ? undefined : exportFormat
        )

        dispatch({ type: 'EXPORT_COMPLETE', id: song.id, outputPath: result.output_path })
        written++

        // Record usage for this export
        try {
          await recordUsage()
        } catch (usageErr) {
          console.error('Failed to record usage:', usageErr)
          // Continue anyway - the export succeeded
        }

        // Add to history
        const profanityCount = profaneWords.length
        const historyEntry = await window.electronAPI.addHistoryEntry({
          originalFileName: song.fileName,
          originalFilePath: song.filePath,
          censoredFilePath: result.output_path,
          dateCreated: Date.now(),
          wordCount: song.words.length,
          profanityCount,
          duration: song.duration,
          language: song.language
        })
        dispatch({ type: 'ADD_HISTORY_ENTRY', entry: historyEntry })
      } catch (err) {
        Sentry.captureException(err)
        const message = err instanceof Error ? err.message : String(err)
        track('song_failed', { stage: 'export', error_kind: errorKind(message) })
        dispatch({ type: 'SET_SONG_ERROR', id: song.id, message })
      }

      completed++
      dispatch({ type: 'EXPORT_ALL_PROGRESS', completed })
    }

    dispatch({ type: 'EXPORT_ALL_COMPLETE' })
    track('export_completed', {
      count: written,
      failed: exportableSongs.length - written,
      format: exportFormat,
      mode: 'batch'
    })
    exportingRef.current = false

    // The rest of the batch didn't fit in the free quota - now that they have
    // what they're owed, make the reason clear.
    if (quotaLimited) {
      openPaywall('batch_truncated')
    }
  }, [state.songs, exportFormat, checkCanProcess, recordUsage, openPaywall, settings.exportFolder])

  // Toggle turbo mode
  const handleToggleTurbo = useCallback((enabled: boolean) => {
    dispatch({ type: 'SET_TURBO_ENABLED', enabled })
    track('turbo_toggled', { enabled })
  }, [])

  // Toggle dual-pass transcription (ad-lib detection)
  const handleToggleDualPass = useCallback((enabled: boolean) => {
    dispatch({ type: 'SET_DUAL_PASS_ENABLED', enabled })
    track('dual_pass_toggled', { enabled })
  }, [])

  // Show paywall modal
  const handleShowPaywall = useCallback(() => {
    openPaywall('upgrade_click')
  }, [openPaywall])

  // If still loading auth, show loading screen
  if (authLoading) {
    return (
      <div className="min-h-screen bg-app flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block w-8 h-8 border-2 border-border-strong border-t-blue-400 rounded-full animate-spin mb-3" />
          <p className="text-text-secondary">Loading...</p>
        </div>
      </div>
    )
  }

  // If not authenticated, show auth screen
  if (!isAuthenticated) {
    return <AuthScreen />
  }

  // Computed values
  const readyCount = state.songs.filter((s) => s.status === 'ready').length
  const completedCount = state.songs.filter((s) => s.status === 'completed').length
  const isProcessing = state.currentlyProcessingId !== null
  const importDisabled = !state.backendReady || modelStatus !== 'ready'
  const queuedPaths = new Set(state.songs.map((s) => s.filePath))
  return (
    <div className="h-screen flex flex-col bg-app text-text-primary">
      {/* Header */}
      <header className="drag-region border-b border-border px-6 py-4 shrink-0">
        <div className="flex items-center justify-between no-drag">
          <div>
            <h1 className="text-xl font-bold">Cleanse <span className="text-xs font-normal text-text-disabled">v{pkg.version}</span></h1>
            <p className="text-sm text-text-secondary">Batch censor profanity in audio files</p>
          </div>
          <div className="flex items-center gap-3">
            {/* Help button */}
            <button
              onClick={() => {
                track('screen_view', { screen_name: 'help' })
                setShowHelp(true)
              }}
              className="w-5 h-5 rounded-full border border-border-strong text-text-secondary hover:text-text-primary hover:border-border-strong text-xs font-medium transition-colors flex items-center justify-center"
              title="Quick reference"
            >
              ?
            </button>

            {/* Feedback button */}
            <button
              onClick={() => {
                track('screen_view', { screen_name: 'feedback' })
                setShowFeedback(true)
              }}
              className="text-xs text-text-secondary hover:text-text-primary transition-colors"
            >
              Feedback
            </button>

            {/* Divider */}
            <span className="text-text-disabled">|</span>

            {/* Dual-pass toggle (ad-lib detection) */}
            <DualPassToggle
              enabled={state.dualPassEnabled}
              isProcessing={isProcessing}
              onToggle={handleToggleDualPass}
            />

            {/* Turbo toggle */}
            <TurboToggle
              turboEnabled={state.turboEnabled}
              deviceInfo={state.deviceInfo}
              isProcessing={isProcessing}
              onToggle={handleToggleTurbo}
            />

            {/* Divider */}
            <span className="text-text-disabled">|</span>

            {/* Custom words */}
            <button
              onClick={() => {
                track('screen_view', { screen_name: 'custom_words' })
                setShowCustomWords(true)
              }}
              className="text-xs text-text-tertiary hover:text-text-primary transition-colors px-2 py-1 rounded hover:bg-muted"
              title="Custom profanity word list"
            >
              Custom Words{state.customProfanityWords.length > 0 ? ` (${state.customProfanityWords.length})` : ''}
            </button>

            {/* Theme toggle */}
            <ThemeToggle />

            {/* Free quota, always visible so the limit isn't a surprise */}
            <UsageIndicator onManageSubscription={handleShowPaywall} />

            {/* User menu */}
            <UserMenu onManageSubscription={handleShowPaywall} />

            {/* Backend status */}
            <div className="flex items-center gap-2">
              <span
                className={`inline-block w-2 h-2 rounded-full ${
                  state.backendReady && modelStatus === 'ready'
                    ? 'bg-green-500'
                    : 'bg-yellow-500 animate-pulse'
                }`}
              />
              <span className="text-xs text-text-secondary">
                {!state.backendReady
                  ? 'Starting...'
                  : modelStatus === 'ready'
                    ? 'Ready'
                    : modelStatus === 'loading'
                      ? 'Loading model...'
                      : modelStatus === 'downloading'
                        ? 'Downloading model...'
                        : 'Preparing...'}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Body: library sidebar + main column, each scrolling on its own */}
      <div className="flex flex-1 min-h-0">
        {settings.musicFolder && libraryOpen && (
          <div className="w-80 xl:w-96 shrink-0 min-h-0">
            <MusicFolder
              folder={settings.musicFolder}
              listing={library}
              loading={libraryLoading}
              queuedPaths={queuedPaths}
              disabled={importDisabled}
              notice={importNotice}
              onAdd={(files) => handleFilesSelected(files, 'folder')}
              onChangeFolder={handleChooseMusicFolder}
              onForgetFolder={handleForgetMusicFolder}
              onRefresh={loadLibrary}
              onCollapse={() => setLibraryOpen(false)}
            />
          </div>
        )}
        {settings.musicFolder && !libraryOpen && (
          <button
            onClick={() => setLibraryOpen(true)}
            className="shrink-0 w-7 border-r border-border bg-surface text-text-tertiary hover:text-text-primary hover:bg-elevated flex flex-col items-center pt-3 gap-2"
            title="Show library"
          >
            <span className="text-sm">›</span>
            <span className="text-[10px] uppercase tracking-wider [writing-mode:vertical-rl]">Library</span>
          </button>
        )}

      <div className="flex-1 min-w-0 overflow-y-auto">
      <main className="max-w-4xl mx-auto px-6 py-8 flex flex-col gap-6">
        {/* Model download progress */}
        {state.backendReady && modelStatus !== 'ready' && (
          <div className="bg-surface/50 border border-border-strong rounded-xl p-6 text-center">
            <p className="text-sm font-medium text-text-secondary mb-2">
              {modelDownloadMessage || 'Preparing audio engine...'}
            </p>
            {modelStatus === 'downloading' && modelDownloadProgress > 0 && (
              <div className="w-full bg-muted rounded-full h-2 mb-2">
                <div
                  className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${modelDownloadProgress}%` }}
                />
              </div>
            )}
            <p className="text-xs text-text-tertiary">
              {modelStatus === 'downloading'
                ? 'This only happens once — the model is cached for future use'
                : 'Almost ready...'}
            </p>
          </div>
        )}

        {/* File upload */}
        <FileUpload
          onFilesSelected={handleFilesSelected}
          disabled={importDisabled}
          offerMusicFolder={!settings.musicFolder}
          onChooseMusicFolder={handleChooseMusicFolder}
          notice={importNotice}
        />

        {/* Queue list */}
        {state.songs.length > 0 && (
          <>
            <QueueList
              songs={state.songs}
              expandedSongId={state.expandedSongId}
              globalCensorType={state.globalDefaultCensorType}
              exportFormat={exportFormat}
              onToggleExpand={handleToggleExpand}
              onRemoveSong={handleRemoveSong}
              onRetrySong={retrySong}
              onCancelSong={(id) => { cancelSong(id); dispatch({ type: 'CANCEL_SONG', id }) }}
              onExportSong={handleExportSong}
              renderDetailPanel={(song) => (
                <SongDetailPanel
                  song={song}
                  onToggleProfanity={handleToggleProfanity}
                  onSetCensorType={handleSetWordCensorType}
                  onSetSongCensorType={handleSetSongCensorType}
                  onResetAllWordCensorTypes={handleResetAllWordCensorTypes}
                  onAddManualWord={handleAddManualWord}
                  onRemoveWord={handleRemoveWord}
                  onMarkReviewed={handleMarkReviewed}
                  onClose={handleCloseExpanded}
                />
              )}
            />

            {/* Batch controls */}
            <BatchControls
              songCount={state.songs.length}
              readyCount={readyCount}
              completedCount={completedCount}
              globalCensorType={state.globalDefaultCensorType}
              onSetGlobalCensorType={handleSetGlobalCensorType}
              crossfadeMs={state.crossfadeMs}
              onSetCrossfadeMs={(ms) => dispatch({ type: 'SET_CROSSFADE_MS', ms })}
              paddingMs={state.paddingMs}
              onSetPaddingMs={(ms) => dispatch({ type: 'SET_PADDING_MS', ms })}
              exportFormat={exportFormat}
              onSetExportFormat={handleSetExportFormat}
              onExportAll={handleExportAll}
              onClearAll={handleClearAll}
              isExporting={state.isExportingAll}
              exportProgress={state.exportProgress}
              disabled={isProcessing}
              exportFolder={settings.exportFolder}
              onChangeExportFolder={handleChangeExportFolder}
              onForgetExportFolder={handleForgetExportFolder}
            />
          </>
        )}

        {/* History (show when no songs in queue) */}
        {state.songs.length === 0 && (
          <HistoryList history={state.history} onDelete={handleDeleteHistoryEntry} />
        )}
      </main>
      </div>
      </div>

      {/* Help modal */}
      <HelpModal isOpen={showHelp} onClose={() => setShowHelp(false)} />

      {/* Custom word list modal */}
      {showCustomWords && (
        <CustomWordList
          words={state.customProfanityWords}
          onAddWord={(word) => {
            dispatch({ type: 'ADD_CUSTOM_WORD', word })
            track('custom_word_added', { list_size: state.customProfanityWords.length + 1 })
          }}
          onRemoveWord={(word) => {
            dispatch({ type: 'REMOVE_CUSTOM_WORD', word })
            track('custom_word_removed', { list_size: Math.max(0, state.customProfanityWords.length - 1) })
          }}
          onClose={() => setShowCustomWords(false)}
        />
      )}

      {/* Feedback modal */}
      <FeedbackModal isOpen={showFeedback} onClose={() => setShowFeedback(false)} />

      {/* Paywall modal */}
      <PaywallModal isOpen={showPaywall} onClose={() => setShowPaywall(false)} />

      {/* Update modal */}
      <UpdateModal
        isOpen={updateState.show}
        version={updateState.version}
        releaseNotes={updateState.releaseNotes}
        downloadProgress={updateState.downloadProgress}
        downloaded={updateState.downloaded}
        error={updateState.error}
        onDownload={() => {
          setUpdateState((prev) => ({ ...prev, downloadProgress: 0, error: null }))
          window.electronAPI.downloadUpdate().catch((err) => {
            const message = err instanceof Error ? err.message : String(err)
            setUpdateState((prev) => ({ ...prev, error: message, downloadProgress: null }))
          })
        }}
        onInstall={() => {
          track('update_install_clicked', { version: updateState.version })
          window.electronAPI.installUpdate()
        }}
        onClose={() => {
          track('update_dismissed', { version: updateState.version, downloaded: updateState.downloaded })
          setUpdateState((prev) => ({ ...prev, show: false }))
        }}
      />
    </div>
  )
}

// Wrap the app with providers
export default function App(): React.JSX.Element {
  return (
    <ThemeProvider>
      <AuthProvider>
        <MainApp />
      </AuthProvider>
    </ThemeProvider>
  )
}
