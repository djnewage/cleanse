import { useReducer, useEffect, useCallback } from 'react'
import type { AppState, AppAction, CensorType } from './types'
import { useTranscription } from './hooks/useTranscription'
import { useAudioProcessing } from './hooks/useAudioProcessing'
import FileUpload from './components/FileUpload'
import TranscriptEditor from './components/TranscriptEditor'
import AudioPreview from './components/AudioPreview'
import ExportControls from './components/ExportControls'

const initialState: AppState = {
  status: 'loading-backend',
  backendReady: false,
  filePath: null,
  fileName: null,
  words: [],
  duration: 0,
  language: '',
  defaultCensorType: 'mute',
  censoredFilePath: null,
  errorMessage: null,
  vocalsPath: null,
  accompanimentPath: null
}

function reducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'SET_BACKEND_STATUS':
      return {
        ...state,
        backendReady: action.ready,
        status: action.ready ? (state.filePath ? state.status : 'ready') : 'loading-backend',
        errorMessage: action.error || state.errorMessage
      }
    case 'SET_FILE':
      return {
        ...state,
        filePath: action.path,
        fileName: action.name,
        words: [],
        duration: 0,
        language: '',
        censoredFilePath: null,
        errorMessage: null,
        status: 'ready'
      }
    case 'CLEAR_FILE':
      return { ...initialState, backendReady: state.backendReady, status: 'ready' }
    case 'START_TRANSCRIPTION':
      return { ...state, status: 'transcribing', errorMessage: null, words: [], censoredFilePath: null, vocalsPath: null, accompanimentPath: null }
    case 'TRANSCRIPTION_COMPLETE':
      return {
        ...state,
        status: 'ready',
        words: action.words,
        duration: action.duration,
        language: action.language
      }
    case 'START_SEPARATING':
      return { ...state, status: 'separating', errorMessage: null }
    case 'SEPARATION_COMPLETE':
      return {
        ...state,
        status: 'ready',
        vocalsPath: action.vocalsPath,
        accompanimentPath: action.accompanimentPath
      }
    case 'TOGGLE_PROFANITY':
      return {
        ...state,
        words: state.words.map((w, i) =>
          i === action.index ? { ...w, is_profanity: !w.is_profanity } : w
        ),
        censoredFilePath: null
      }
    case 'SET_CENSOR_TYPE':
      return {
        ...state,
        words: state.words.map((w, i) =>
          i === action.index ? { ...w, censor_type: action.censorType } : w
        ),
        censoredFilePath: null
      }
    case 'SET_DEFAULT_CENSOR_TYPE':
      return { ...state, defaultCensorType: action.censorType, censoredFilePath: null }
    case 'START_CENSORING':
      return { ...state, status: 'censoring', errorMessage: null }
    case 'CENSORING_COMPLETE':
      return { ...state, status: 'ready', censoredFilePath: action.outputPath }
    case 'SET_ERROR':
      return { ...state, status: 'error', errorMessage: action.message }
    case 'CLEAR_ERROR':
      return { ...state, status: 'ready', errorMessage: null }
    default:
      return state
  }
}

export default function App(): React.JSX.Element {
  const [state, dispatch] = useReducer(reducer, initialState)
  const { transcribe } = useTranscription(dispatch)
  const { censor } = useAudioProcessing(dispatch, state.defaultCensorType)

  // Listen for backend status updates from main process
  useEffect(() => {
    const unsubscribe = window.electronAPI.onBackendStatus((status) => {
      dispatch({ type: 'SET_BACKEND_STATUS', ready: status.ready, error: status.error })
    })

    // Also check status on mount
    window.electronAPI.getBackendStatus().then((status) => {
      dispatch({ type: 'SET_BACKEND_STATUS', ready: status.ready })
    })

    return unsubscribe
  }, [])

  const separateVocals = useCallback(
    async (filePath: string) => {
      dispatch({ type: 'START_SEPARATING' })
      try {
        const result = await window.electronAPI.separateAudio(filePath)
        dispatch({
          type: 'SEPARATION_COMPLETE',
          vocalsPath: result.vocals_path,
          accompanimentPath: result.accompaniment_path
        })
      } catch (err) {
        dispatch({ type: 'SET_ERROR', message: (err as Error).message })
      }
    },
    [dispatch]
  )

  const handleFileSelected = useCallback(
    async (path: string, name: string) => {
      dispatch({ type: 'SET_FILE', path, name })
      const ok = await transcribe(path)
      if (ok) {
        // Auto-separate vocals after transcription completes
        separateVocals(path)
      }
    },
    [transcribe, separateVocals]
  )

  const handleToggleProfanity = useCallback((index: number) => {
    dispatch({ type: 'TOGGLE_PROFANITY', index })
  }, [])

  const handleSetCensorType = useCallback((index: number, censorType: CensorType) => {
    dispatch({ type: 'SET_CENSOR_TYPE', index, censorType })
  }, [])

  const handleSetDefaultCensorType = useCallback((censorType: CensorType) => {
    dispatch({ type: 'SET_DEFAULT_CENSOR_TYPE', censorType })
  }, [])

  const handleExport = useCallback(() => {
    if (state.filePath) {
      censor(state.filePath, state.words, state.vocalsPath, state.accompanimentPath)
    }
  }, [state.filePath, state.words, state.vocalsPath, state.accompanimentPath, censor])

  const handleClearFile = useCallback(() => {
    dispatch({ type: 'CLEAR_FILE' })
  }, [])

  const hasProfanity = state.words.some((w) => w.is_profanity)
  const isProcessing = state.status === 'transcribing' || state.status === 'separating' || state.status === 'censoring'

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      {/* Header */}
      <header className="drag-region border-b border-zinc-800 px-6 py-4">
        <div className="flex items-center justify-between no-drag">
          <div>
            <h1 className="text-xl font-bold">Clean Song Editor</h1>
            <p className="text-sm text-zinc-500">Censor profanity in audio files</p>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                state.backendReady ? 'bg-green-500' : 'bg-yellow-500 animate-pulse'
              }`}
            />
            <span className="text-xs text-zinc-500">
              {state.backendReady ? 'Backend ready' : 'Starting backend...'}
            </span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-3xl mx-auto px-6 py-8 flex flex-col gap-6">
        {/* Error banner */}
        {state.errorMessage && (
          <div className="bg-red-950/50 border border-red-800 rounded-lg px-4 py-3 flex items-start justify-between">
            <p className="text-sm text-red-300">{state.errorMessage}</p>
            <button
              onClick={() => dispatch({ type: 'CLEAR_ERROR' })}
              className="text-red-500 hover:text-red-300 ml-3 text-lg leading-none"
            >
              &times;
            </button>
          </div>
        )}

        {/* File upload or current file */}
        {!state.filePath ? (
          <FileUpload
            onFileSelected={handleFileSelected}
            disabled={!state.backendReady}
          />
        ) : (
          <div className="flex items-center justify-between bg-zinc-900/50 rounded-lg px-4 py-3 border border-zinc-800">
            <div className="flex items-center gap-3">
              <span className="text-2xl">🎵</span>
              <div>
                <p className="font-medium">{state.fileName}</p>
                <p className="text-xs text-zinc-500">{state.filePath}</p>
              </div>
            </div>
            <button
              onClick={handleClearFile}
              disabled={isProcessing}
              className="text-sm text-zinc-500 hover:text-zinc-300 disabled:opacity-30"
            >
              Change file
            </button>
          </div>
        )}

        {/* Transcription status */}
        {state.status === 'transcribing' && (
          <div className="text-center py-8">
            <div className="inline-block w-8 h-8 border-2 border-zinc-600 border-t-blue-400 rounded-full animate-spin mb-3" />
            <p className="text-zinc-400">Transcribing audio...</p>
            <p className="text-xs text-zinc-600 mt-1">
              This may take a moment for the first run while the model loads
            </p>
          </div>
        )}

        {/* Vocal separation status */}
        {state.status === 'separating' && (
          <div className="text-center py-8">
            <div className="inline-block w-8 h-8 border-2 border-zinc-600 border-t-purple-400 rounded-full animate-spin mb-3" />
            <p className="text-zinc-400">Separating vocals...</p>
            <p className="text-xs text-zinc-600 mt-1">
              Isolating vocals from instrumentals (~60-120 seconds)
            </p>
          </div>
        )}

        {/* Transcript editor */}
        {state.words.length > 0 && state.status !== 'transcribing' && (
          <>
            <TranscriptEditor
              words={state.words}
              onToggleProfanity={handleToggleProfanity}
              onSetCensorType={handleSetCensorType}
              defaultCensorType={state.defaultCensorType}
              language={state.language}
              duration={state.duration}
            />

            <ExportControls
              onExport={handleExport}
              disabled={isProcessing}
              hasProfanity={hasProfanity}
              isCensoring={state.status === 'censoring'}
              defaultCensorType={state.defaultCensorType}
              onSetDefaultCensorType={handleSetDefaultCensorType}
            />
          </>
        )}

        {/* Audio previews */}
        {(state.filePath || state.censoredFilePath) &&
          state.words.length > 0 &&
          !isProcessing && (
            <AudioPreview
              originalPath={state.filePath}
              censoredPath={state.censoredFilePath}
            />
          )}
      </main>
    </div>
  )
}
