import { useCallback, useState } from 'react'
import type { ImportSource } from '../types'
import { AUDIO_EXTENSIONS_LABEL, isAudioFileName } from '../../../shared/audioExtensions'
import { LIBRARY_DRAG_TYPE } from '../lib/library'

interface FileUploadProps {
  onFilesSelected: (files: Array<{ path: string; name: string }>, source: ImportSource) => void
  disabled: boolean
  /** 'none': no folder yet, offer to set one up. 'collapsed': a folder is
   * set but the sidebar is hidden — the thin tab alone was easy to miss, so
   * the drop zone also points at it. 'open': nothing to add. */
  library: 'none' | 'collapsed' | 'open'
  onChooseMusicFolder: () => void
  onShowLibrary: () => void
  /** "2 already in the queue" and the like, shown for a moment after an import. */
  notice: string | null
}

export default function FileUpload({
  onFilesSelected,
  disabled,
  library,
  onChooseMusicFolder,
  onShowLibrary,
  notice
}: FileUploadProps): React.JSX.Element {
  const [isDragging, setIsDragging] = useState(false)

  const handleClick = useCallback(async () => {
    const filePaths = await window.electronAPI.selectAudioFiles()
    if (filePaths.length > 0) {
      const files = filePaths.map((path) => ({
        path,
        name: path.split(/[\\/]/).pop() || path
      }))
      onFilesSelected(files, 'picker')
    }
  }, [onFilesSelected])

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      if (!disabled) setIsDragging(true)
    },
    [disabled]
  )

  const handleDragLeave = useCallback(() => {
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      if (disabled) return

      // Rows dragged from the library sidebar carry their paths directly;
      // they were never OS files on the clipboard.
      const fromLibrary = e.dataTransfer.getData(LIBRARY_DRAG_TYPE)
      if (fromLibrary) {
        try {
          const files = JSON.parse(fromLibrary) as Array<{ path: string; name: string }>
          if (Array.isArray(files) && files.length > 0) onFilesSelected(files, 'folder')
        } catch {
          /* not ours after all */
        }
        return
      }

      const droppedFiles = e.dataTransfer.files
      const validFiles: Array<{ path: string; name: string }> = []

      for (let i = 0; i < droppedFiles.length; i++) {
        const file = droppedFiles[i]
        if (isAudioFileName(file.name)) {
          const filePath = window.electronAPI.getPathForFile(file)
          if (filePath) {
            validFiles.push({ path: filePath, name: file.name })
          }
        }
      }

      if (validFiles.length > 0) {
        onFilesSelected(validFiles, 'drop')
      }
    },
    [disabled, onFilesSelected]
  )

  return (
    <div
      onClick={disabled ? undefined : handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`
        border-2 border-dashed rounded-xl p-10 text-center transition-all
        ${disabled ? 'border-border-strong bg-surface/50 text-text-disabled cursor-not-allowed' : 'cursor-pointer'}
        ${isDragging ? 'border-blue-400 bg-blue-950/30 text-blue-300' : ''}
        ${!disabled && !isDragging ? 'border-border-strong bg-surface/30 text-text-secondary hover:border-border-strong hover:text-text-secondary' : ''}
      `}
    >
      <div className="text-4xl mb-3">🎵</div>
      <p className="text-lg font-medium mb-1">
        {disabled ? 'Waiting for backend...' : 'Drop audio files here'}
      </p>
      <p className="text-sm opacity-60">
        {disabled
          ? 'The Python backend is starting up'
          : library === 'open'
            ? 'or click to browse • or pick from your library on the left'
            : 'or click to browse • Select multiple files'}
      </p>
      <p className="text-xs opacity-40 mt-2">{AUDIO_EXTENSIONS_LABEL}</p>
      {library === 'none' && !disabled && (
        <button
          onClick={(e) => {
            e.stopPropagation() // not the file picker
            onChooseMusicFolder()
          }}
          className="mt-4 text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2"
        >
          Choose your music folder to browse it here
        </button>
      )}
      {library === 'collapsed' && !disabled && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onShowLibrary()
          }}
          className="mt-4 text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2"
        >
          Show your music library
        </button>
      )}
      {notice && <p className="mt-3 text-xs text-amber-400">{notice}</p>}
    </div>
  )
}
