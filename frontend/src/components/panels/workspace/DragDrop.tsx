/**
 * Xử lý kéo-thả file để tải lên: preventDefault trên dragover/drop, đọc
 * DataTransfer.files rồi gọi `onFiles`. Trả cả cờ `isDragging` để bật lớp nền.
 */
import { useCallback, useState, type DragEvent } from 'react'

export function useDropZone(onFiles: (files: File[]) => void) {
  const [isDragging, setDragging] = useState(false)

  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault()
    if (e.dataTransfer.types.includes('Files')) setDragging(true)
  }, [])

  const onDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault()
    if (e.currentTarget === e.target) setDragging(false)
  }, [])

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault()
      setDragging(false)
      const files = Array.from(e.dataTransfer.files)
      if (files.length) onFiles(files)
    },
    [onFiles],
  )

  return { isDragging, onDragOver, onDragLeave, onDrop }
}
