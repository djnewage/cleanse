import { useReducer, useEffect, useCallback, useRef, useState } from 'react'
import type {
  BatchAppState,
  BatchAppAction,
  CensorType,
  SongEntry,
  CensorWord
} from './types'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { useQueueProcessor } from './hooks/useQueueProcessor'
import FileUpload from './components/FileUpload'
import QueueList from './components/QueueList'
import BatchControls from './components/BatchControls'
import SongDetailPanel from './components/SongDetailPanel'
import HistoryList from './components/HistoryList'
import AuthScreen from './components/AuthScreen'
import UsageIndicator from './components/UsageIndicator'
import PaywallModal from './components/PaywallModal'
import TurboToggle from './components/TurboToggle'

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
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
  deviceInfo: null
}

function reducer(state: BatchAppState, action: BatchAppAction): BatchAppState {
  switch (action.type) {
    case 'SET_BACKEND_STATUS':
      return { ...state, backendReady: action.ready }

    case 'ADD_SONGS': {
      const newSongs: SongEntry[] = action.songs.map((s) => ({
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
        censoredFilePath: null,
        defaultCensorType: state.globalDefaultCensorType,
        userReviewed: false,
        errorMessage: null
      }))
      const newIds = newSongs.map((s) => s.id)
      return {
        ...state,
        songs: [...state.songs, ...newSongs],
        processingQueue: [...state.processingQueue, ...newIds]
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

    case 'START_TRANSCRIPTION':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id ? { ...s, status: 'transcribing', errorMessage: null } : s
        )
      }

    case 'TRANSCRIPTION_COMPLETE':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.id
            ? { ...s, words: action.words, duration: action.duration, language: action.language }
            : s
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

    case 'TOGGLE_PROFANITY':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.songId
            ? {
                ...s,
                words: s.words.map((w, i) =>
                  i === action.wordIndex ? { ...w, is_profanity: !w.is_profanity } : w
                ),
                censoredFilePath: null
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
                words: s.words.map((w, i) =>
                  i === action.wordIndex ? { ...w, censor_type: action.censorType } : w
                ),
                censoredFilePath: null
              }
            : s
        )
      }

    case 'SET_SONG_CENSOR_TYPE':
      return {
        ...state,
        songs: state.songs.map((s) =>
          s.id === action.songId ? { ...s, defaultCensorType: action.censorType, censoredFilePath: null } : s
        )
      }

    case 'SET_GLOBAL_CENSOR_TYPE':
      return {
        ...state,
        globalDefaultCensorType: action.censorType,
        songs: state.songs.map((s) =>
          s.status === 'pending' ? { ...s, defaultCensorType: action.censorType } : s
        )
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
            ? { ...s, status: 'pending', errorMessage: null, words: [], vocalsPath: null, accompanimentPath: null }
            : s
        ),
        processingQueue: [...state.processingQueue, action.id]
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

    default:
      return state
  }
}

function MainApp(): React.JSX.Element {
  const [state, dispatch] = useReducer(reducer, initialState)
  const exportingRef = useRef(false)
  const [showPaywall, setShowPaywall] = useState(false)

  const { isAuthenticated, isLoading: authLoading, checkCanProcess, recordUsage } = useAuth()

  // Use the queue processor hook
  const { retrySong } = useQueueProcessor({
    songs: state.songs,
    currentlyProcessingId: state.currentlyProcessingId,
    processingQueue: state.processingQueue,
    turboEnabled: state.turboEnabled,
    dispatch
  })

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

  // Listen for device info (main process sends this after backend is ready)
  useEffect(() => {
    const unsubscribe = window.electronAPI.onDeviceInfo((info) => {
      dispatch({ type: 'SET_DEVICE_INFO', deviceInfo: info })
    })

    // Fetch only if backend is already ready (handles late-mount / hot-reload)
    if (state.backendReady) {
      window.electronAPI.getDeviceInfo().then((info) => {
        dispatch({ type: 'SET_DEVICE_INFO', deviceInfo: info })
      }).catch(() => {
        // Will get it from the event
      })
    }

    return unsubscribe
  }, [state.backendReady])

  // Load history on mount
  useEffect(() => {
    window.electronAPI.getHistory().then((history) => {
      dispatch({ type: 'SET_HISTORY', history })
    })
  }, [])

  // Handle file selection
  const handleFilesSelected = useCallback(
    (files: Array<{ path: string; name: string }>) => {
      dispatch({
        type: 'ADD_SONGS',
        songs: files.map((f) => ({ filePath: f.path, fileName: f.name }))
      })
    },
    []
  )

  // Toggle expanded song
  const handleToggleExpand = useCallback((id: string) => {
    dispatch({
      type: 'SET_EXPANDED_SONG',
      id: state.expandedSongId === id ? null : id
    })
  }, [state.expandedSongId])

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
  }, [])

  // Toggle profanity for a word
  const handleToggleProfanity = useCallback((songId: string, wordIndex: number) => {
    dispatch({ type: 'TOGGLE_PROFANITY', songId, wordIndex })
  }, [])

  // Set censor type for a word
  const handleSetWordCensorType = useCallback(
    (songId: string, wordIndex: number, censorType: CensorType) => {
      dispatch({ type: 'SET_WORD_CENSOR_TYPE', songId, wordIndex, censorType })
    },
    []
  )

  // Set censor type for a song
  const handleSetSongCensorType = useCallback((songId: string, censorType: CensorType) => {
    dispatch({ type: 'SET_SONG_CENSOR_TYPE', songId, censorType })
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

  // Export all ready songs with paywall check
  const handleExportAll = useCallback(async () => {
    if (exportingRef.current) return

    // Check if user can process
    const usageInfo = await checkCanProcess()
    if (!usageInfo.canProcess) {
      setShowPaywall(true)
      return
    }

    exportingRef.current = true

    const exportableSongs = state.songs.filter(
      (s) => (s.status === 'ready' || s.status === 'completed') && s.words.some((w) => w.is_profanity)
    )

    if (exportableSongs.length === 0) {
      exportingRef.current = false
      return
    }

    // Check if user has enough quota for all songs
    if (!usageInfo.isSubscribed && exportableSongs.length > usageInfo.songsRemaining) {
      // Show paywall if they're trying to export more than their remaining quota
      setShowPaywall(true)
      exportingRef.current = false
      return
    }

    // Ask for output directory
    const outputDir = await window.electronAPI.selectOutputDirectory()
    if (!outputDir) {
      exportingRef.current = false
      return
    }

    dispatch({ type: 'START_EXPORT_ALL', total: exportableSongs.length })

    let completed = 0
    let successfulExports = 0

    for (const song of exportableSongs) {
      dispatch({ type: 'START_EXPORT', id: song.id })

      try {
        const profaneWords = song.words.filter((w) => w.is_profanity)
        const censorWords: CensorWord[] = profaneWords.map((w) => ({
          word: w.word,
          start: w.start,
          end: w.end,
          censor_type: w.censor_type ?? song.defaultCensorType
        }))

        const baseName = song.fileName
        const ext = baseName.split('.').pop() || 'mp3'
        const cleanName = baseName.replace(`.${ext}`, `_clean.${ext}`)
        const outputPath = `${outputDir}/${cleanName}`

        const result = await window.electronAPI.censorAudio(
          song.filePath,
          censorWords,
          outputPath,
          song.vocalsPath ?? undefined,
          song.accompanimentPath ?? undefined
        )

        dispatch({ type: 'EXPORT_COMPLETE', id: song.id, outputPath: result.output_path })

        // Record usage for this export
        try {
          await recordUsage()
          successfulExports++
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
        const message = err instanceof Error ? err.message : String(err)
        dispatch({ type: 'SET_SONG_ERROR', id: song.id, message })
      }

      completed++
      dispatch({ type: 'EXPORT_ALL_PROGRESS', completed })
    }

    dispatch({ type: 'EXPORT_ALL_COMPLETE' })
    exportingRef.current = false
  }, [state.songs, checkCanProcess, recordUsage])

  // Toggle turbo mode
  const handleToggleTurbo = useCallback((enabled: boolean) => {
    dispatch({ type: 'SET_TURBO_ENABLED', enabled })
  }, [])

  // Show paywall modal
  const handleShowPaywall = useCallback(() => {
    setShowPaywall(true)
  }, [])

  // If still loading auth, show loading screen
  if (authLoading) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block w-8 h-8 border-2 border-zinc-600 border-t-blue-400 rounded-full animate-spin mb-3" />
          <p className="text-zinc-400">Loading...</p>
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
  const expandedSong = state.expandedSongId
    ? state.songs.find((s) => s.id === state.expandedSongId)
    : null

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      {/* Header */}
      <header className="drag-region border-b border-zinc-800 px-6 py-4">
        <div className="flex items-center justify-between no-drag">
          <div>
            <h1 className="text-xl font-bold">Cleanse</h1>
            <p className="text-sm text-zinc-500">Batch censor profanity in audio files</p>
          </div>
          <div className="flex items-center gap-4">
            {/* Usage indicator */}
            <UsageIndicator onManageSubscription={handleShowPaywall} />

            {/* Turbo toggle */}
            <TurboToggle
              turboEnabled={state.turboEnabled}
              deviceInfo={state.deviceInfo}
              isProcessing={isProcessing}
              onToggle={handleToggleTurbo}
            />

            {/* Backend status */}
            <div className="flex items-center gap-2">
              <span
                className={`inline-block w-2 h-2 rounded-full ${
                  state.backendReady ? 'bg-green-500' : 'bg-yellow-500 animate-pulse'
                }`}
              />
              <span className="text-xs text-zinc-500">
                {state.backendReady ? 'Ready' : 'Starting...'}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-4xl mx-auto px-6 py-8 flex flex-col gap-6">
        {/* File upload */}
        <FileUpload onFilesSelected={handleFilesSelected} disabled={!state.backendReady} />

        {/* Queue list */}
        {state.songs.length > 0 && (
          <>
            <QueueList
              songs={state.songs}
              expandedSongId={state.expandedSongId}
              onToggleExpand={handleToggleExpand}
              onRemoveSong={handleRemoveSong}
              onRetrySong={retrySong}
            />

            {/* Expanded song detail panel */}
            {expandedSong && (
              <SongDetailPanel
                song={expandedSong}
                onToggleProfanity={handleToggleProfanity}
                onSetCensorType={handleSetWordCensorType}
                onSetSongCensorType={handleSetSongCensorType}
                onMarkReviewed={handleMarkReviewed}
                onClose={handleCloseExpanded}
              />
            )}

            {/* Batch controls */}
            <BatchControls
              songCount={state.songs.length}
              readyCount={readyCount}
              completedCount={completedCount}
              globalCensorType={state.globalDefaultCensorType}
              onSetGlobalCensorType={handleSetGlobalCensorType}
              onExportAll={handleExportAll}
              onClearAll={handleClearAll}
              isExporting={state.isExportingAll}
              exportProgress={state.exportProgress}
              disabled={isProcessing}
            />
          </>
        )}

        {/* History (show when no songs in queue) */}
        {state.songs.length === 0 && (
          <HistoryList history={state.history} onDelete={handleDeleteHistoryEntry} />
        )}
      </main>

      {/* Paywall modal */}
      <PaywallModal isOpen={showPaywall} onClose={() => setShowPaywall(false)} />
    </div>
  )
}

// Wrap the app with AuthProvider
export default function App(): React.JSX.Element {
  return (
    <AuthProvider>
      <MainApp />
    </AuthProvider>
  )
}
