export interface TranscribedWord {
  word: string
  start: number
  end: number
  confidence: number
  is_profanity: boolean
  censor_type?: CensorType
}

export interface CensorWord {
  word: string
  start: number
  end: number
  censor_type: CensorType
}

export type CensorType = 'mute' | 'beep' | 'reverse'

export interface SeparationProgress {
  step: string
  progress: number
  message: string
}

export interface HistoryEntry {
  id: string
  originalFileName: string
  originalFilePath: string
  censoredFilePath: string
  dateCreated: number
  wordCount: number
  profanityCount: number
  duration: number
  language: string
}

// Batch Processing Types
export type SongStatus = 'pending' | 'transcribing' | 'separating' | 'ready' | 'exporting' | 'completed' | 'error'

export interface SongEntry {
  id: string
  filePath: string
  fileName: string
  status: SongStatus
  words: TranscribedWord[]
  duration: number
  language: string
  vocalsPath: string | null
  accompanimentPath: string | null
  separationProgress: SeparationProgress | null
  censoredFilePath: string | null
  defaultCensorType: CensorType
  userReviewed: boolean
  errorMessage: string | null
}

export interface BatchAppState {
  backendReady: boolean
  globalDefaultCensorType: CensorType
  songs: SongEntry[]
  currentlyProcessingId: string | null
  processingQueue: string[]
  expandedSongId: string | null
  history: HistoryEntry[]
  isExportingAll: boolean
  exportProgress: { completed: number; total: number } | null
}

export type BatchAppAction =
  | { type: 'SET_BACKEND_STATUS'; ready: boolean; error?: string }
  | { type: 'ADD_SONGS'; songs: Array<{ filePath: string; fileName: string }> }
  | { type: 'REMOVE_SONG'; id: string }
  | { type: 'CLEAR_ALL_SONGS' }
  | { type: 'SET_EXPANDED_SONG'; id: string | null }
  | { type: 'START_PROCESSING'; id: string }
  | { type: 'START_TRANSCRIPTION'; id: string }
  | { type: 'TRANSCRIPTION_COMPLETE'; id: string; words: TranscribedWord[]; duration: number; language: string }
  | { type: 'START_SEPARATING'; id: string }
  | { type: 'SEPARATION_PROGRESS'; id: string; progress: SeparationProgress }
  | { type: 'SEPARATION_COMPLETE'; id: string; vocalsPath: string; accompanimentPath: string }
  | { type: 'SET_SONG_READY'; id: string }
  | { type: 'SET_SONG_ERROR'; id: string; message: string }
  | { type: 'TOGGLE_PROFANITY'; songId: string; wordIndex: number }
  | { type: 'SET_WORD_CENSOR_TYPE'; songId: string; wordIndex: number; censorType: CensorType }
  | { type: 'SET_SONG_CENSOR_TYPE'; songId: string; censorType: CensorType }
  | { type: 'SET_GLOBAL_CENSOR_TYPE'; censorType: CensorType }
  | { type: 'MARK_SONG_REVIEWED'; id: string }
  | { type: 'START_EXPORT'; id: string }
  | { type: 'EXPORT_COMPLETE'; id: string; outputPath: string }
  | { type: 'START_EXPORT_ALL'; total: number }
  | { type: 'EXPORT_ALL_PROGRESS'; completed: number }
  | { type: 'EXPORT_ALL_COMPLETE' }
  | { type: 'RETRY_SONG'; id: string }
  | { type: 'PROCESSING_COMPLETE'; id: string }
  | { type: 'SET_HISTORY'; history: HistoryEntry[] }
  | { type: 'ADD_HISTORY_ENTRY'; entry: HistoryEntry }
  | { type: 'DELETE_HISTORY_ENTRY'; id: string }

// Legacy single-file types (for backwards compatibility)
export type AppStatus = 'idle' | 'loading-backend' | 'ready' | 'transcribing' | 'separating' | 'censoring' | 'error'

export interface AppState {
  status: AppStatus
  backendReady: boolean
  filePath: string | null
  fileName: string | null
  words: TranscribedWord[]
  duration: number
  language: string
  defaultCensorType: CensorType
  censoredFilePath: string | null
  errorMessage: string | null
  vocalsPath: string | null
  accompanimentPath: string | null
  separationProgress: SeparationProgress | null
  history: HistoryEntry[]
}

export type AppAction =
  | { type: 'SET_BACKEND_STATUS'; ready: boolean; error?: string }
  | { type: 'SET_FILE'; path: string; name: string }
  | { type: 'CLEAR_FILE' }
  | { type: 'START_TRANSCRIPTION' }
  | { type: 'TRANSCRIPTION_COMPLETE'; words: TranscribedWord[]; duration: number; language: string }
  | { type: 'TOGGLE_PROFANITY'; index: number }
  | { type: 'SET_CENSOR_TYPE'; index: number; censorType: CensorType }
  | { type: 'SET_DEFAULT_CENSOR_TYPE'; censorType: CensorType }
  | { type: 'START_SEPARATING' }
  | { type: 'SEPARATION_COMPLETE'; vocalsPath: string; accompanimentPath: string }
  | { type: 'START_CENSORING' }
  | { type: 'CENSORING_COMPLETE'; outputPath: string }
  | { type: 'SET_ERROR'; message: string }
  | { type: 'CLEAR_ERROR' }
  | { type: 'SET_SEPARATION_PROGRESS'; progress: SeparationProgress }
  | { type: 'SET_HISTORY'; history: HistoryEntry[] }
  | { type: 'ADD_HISTORY_ENTRY'; entry: HistoryEntry }
  | { type: 'DELETE_HISTORY_ENTRY'; id: string }

// Auth & Subscription Types
export type SubscriptionStatus = 'none' | 'active' | 'canceled' | 'past_due'

export interface UserSubscription {
  status: SubscriptionStatus
  stripeCustomerId: string | null
  stripeSubscriptionId: string | null
  currentPeriodEnd: number | null
}

export interface UserData {
  email: string
  createdAt: number
  songsProcessed: number
  subscription: UserSubscription
}

export interface AuthState {
  isAuthenticated: boolean
  isLoading: boolean
  user: {
    uid: string
    email: string | null
  } | null
  userData: UserData | null
  error: string | null
}

export interface UsageInfo {
  canProcess: boolean
  songsProcessed: number
  songsRemaining: number
  isSubscribed: boolean
}

export const FREE_SONGS_LIMIT = 5
