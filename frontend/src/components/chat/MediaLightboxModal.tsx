import React, { useState, useRef, useEffect, useCallback } from 'react'
import {
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Maximize2,
  Download,
  X,
  ExternalLink,
  Play,
  Pause,
  Volume2,
  VolumeX,
  Repeat,
} from 'lucide-react'

export interface LightboxMediaProps {
  type?: 'image' | 'video'
  src: string
  poster?: string
  caption?: string
  sourceUrl?: string
  duration?: number
  onClose?: () => void
}

/**
 * Trình xem đa phương tiện tương tác (MediaLightboxModal).
 * - Hỗ trợ cả Hình ảnh (Screenshots) lẫn Video (Screen Recordings).
 * - Video Controls: Play/Pause, Seek Timeline, Speed (0.5x, 1x, 2x), Mute/Unmute, Loop.
 * - Thu phóng bằng con lăn chuột (Wheel Zoom từ 50% đến 400%).
 * - Kéo rê ảnh/video tự do (Pan & Drag khi di chuyển chuột).
 * - Phím tắt hỗ trợ: Space (Play/Pause), ESC (Close), Arrow keys (Seek / Pan).
 */
export function MediaLightboxModal({
  type = 'image',
  src,
  poster,
  caption,
  sourceUrl,
  duration,
  onClose,
}: LightboxMediaProps) {
  const [scale, setScale] = useState(1)
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })

  // Video State
  const [isPlaying, setIsPlaying] = useState(true)
  const [isMuted, setIsMuted] = useState(true)
  const [isLooping, setIsLooping] = useState(true)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [currentTime, setCurrentTime] = useState(0)
  const [videoDuration, setVideoDuration] = useState(duration || 0)

  const containerRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)

  // Reset transform
  const handleReset = useCallback(() => {
    setScale(1)
    setPosition({ x: 0, y: 0 })
  }, [])

  // Zoom controls
  const handleZoomIn = useCallback(() => {
    setScale((prev) => Math.min(4, Number((prev + 0.25).toFixed(2))))
  }, [])

  const handleZoomOut = useCallback(() => {
    setScale((prev) => Math.max(0.5, Number((prev - 0.25).toFixed(2))))
  }, [])

  // Wheel zoom
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    const delta = e.deltaY < 0 ? 0.15 : -0.15
    setScale((prev) => {
      const next = Math.min(4, Math.max(0.5, Number((prev + delta).toFixed(2))))
      return next
    })
  }, [])

  // Drag & Pan handlers
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (scale <= 1) return
      setIsDragging(true)
      setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y })
    },
    [scale, position],
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!isDragging) return
      setPosition({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      })
    },
    [isDragging, dragStart],
  )

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
  }, [])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose?.()
      } else if (e.key === '0' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        handleReset()
      } else if (e.key === '+' || e.key === '=') {
        handleZoomIn()
      } else if (e.key === '-') {
        handleZoomOut()
      } else if (e.code === 'Space' && type === 'video') {
        e.preventDefault()
        togglePlay()
      } else if (e.key === 'ArrowLeft' && type === 'video' && videoRef.current) {
        videoRef.current.currentTime = Math.max(0, videoRef.current.currentTime - 5)
      } else if (e.key === 'ArrowRight' && type === 'video' && videoRef.current) {
        videoRef.current.currentTime = Math.min(videoDuration, videoRef.current.currentTime + 5)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose, handleReset, handleZoomIn, handleZoomOut, type, videoDuration])

  // Download Handler
  const handleDownload = () => {
    const link = document.createElement('a')
    link.href = src
    const ext = type === 'video' ? 'mp4' : 'png'
    link.download = `boxfox-${type}-capture-${Date.now()}.${ext}`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  // Video Controls Handlers
  const togglePlay = () => {
    if (!videoRef.current) return
    if (isPlaying) {
      videoRef.current.pause()
      setIsPlaying(false)
    } else {
      videoRef.current.play()
      setIsPlaying(true)
    }
  }

  const toggleMute = () => {
    if (!videoRef.current) return
    videoRef.current.muted = !isMuted
    setIsMuted(!isMuted)
  }

  const cycleSpeed = () => {
    const speeds = [0.5, 1, 1.5, 2]
    const nextIndex = (speeds.indexOf(playbackRate) + 1) % speeds.length
    const nextSpeed = speeds[nextIndex]
    setPlaybackRate(nextSpeed)
    if (videoRef.current) {
      videoRef.current.playbackRate = nextSpeed
    }
  }

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const seekTime = Number(e.target.value)
    setCurrentTime(seekTime)
    if (videoRef.current) {
      videoRef.current.currentTime = seekTime
    }
  }

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-50 flex flex-col items-center justify-between bg-black/90 p-4 select-none backdrop-blur-md animate-in fade-in duration-200"
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      {/* Top Header Bar */}
      <div className="flex w-full max-w-5xl items-center justify-between px-2 pt-2 z-10">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 rounded-lg bg-panel2/80 px-3 py-1.5 border border-line/60 text-xs font-medium text-fg shadow-lg">
            <span className="flex size-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="font-semibold text-fg">
              {type === 'video' ? 'Session Screen Recording' : 'Browser Screen Capture'}
            </span>
            {caption && <span className="text-muted font-normal">• {caption}</span>}
          </div>

          {sourceUrl && (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 rounded-lg bg-panel2/60 hover:bg-panel2 px-2.5 py-1.5 border border-line/40 text-xs text-muted hover:text-fg transition"
            >
              <ExternalLink className="size-3.5" />
              <span className="truncate max-w-[200px]">{sourceUrl}</span>
            </a>
          )}
        </div>

        {/* Close Button */}
        <button
          type="button"
          onClick={onClose}
          className="flex size-9 items-center justify-center rounded-xl bg-panel2/80 hover:bg-panel2 border border-line/60 text-muted hover:text-fg transition cursor-pointer shadow-lg"
          title="Close (ESC)"
        >
          <X className="size-5" />
        </button>
      </div>

      {/* Main Media Viewport */}
      <div className="relative flex-1 w-full flex items-center justify-center overflow-hidden my-auto cursor-grab active:cursor-grabbing">
        {type === 'video' ? (
          <div
            style={{
              transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
              transition: isDragging ? 'none' : 'transform 0.1s ease-out',
            }}
            className="relative max-h-[75vh] max-w-[85vw] rounded-xl overflow-hidden shadow-2xl border border-line/80 bg-panel2"
          >
            <video
              ref={videoRef}
              src={src}
              poster={poster}
              autoPlay
              loop={isLooping}
              muted={isMuted}
              playsInline
              onTimeUpdate={() => {
                if (videoRef.current) {
                  setCurrentTime(videoRef.current.currentTime)
                  if (!videoDuration && videoRef.current.duration) {
                    setVideoDuration(videoRef.current.duration)
                  }
                }
              }}
              onLoadedMetadata={() => {
                if (videoRef.current) {
                  setVideoDuration(videoRef.current.duration)
                }
              }}
              className="max-h-[75vh] max-w-[85vw] object-contain rounded-xl"
              onClick={togglePlay}
            />

            {/* Play Overlay Button when paused */}
            {!isPlaying && (
              <button
                type="button"
                onClick={togglePlay}
                className="absolute inset-0 m-auto flex size-16 items-center justify-center rounded-full bg-black/60 text-white border border-white/20 hover:scale-110 transition cursor-pointer backdrop-blur-sm shadow-xl"
              >
                <Play className="size-8 ml-1 fill-white" />
              </button>
            )}
          </div>
        ) : (
          <img
            src={src}
            alt={caption || 'Screen capture preview'}
            style={{
              transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
              transition: isDragging ? 'none' : 'transform 0.1s ease-out',
            }}
            className="max-h-[78vh] max-w-[88vw] object-contain rounded-xl shadow-2xl border border-line/80 bg-panel2"
            draggable={false}
            onDoubleClick={() => {
              if (scale === 1) setScale(2)
              else handleReset()
            }}
          />
        )}
      </div>

      {/* Floating Controls Bar */}
      <div className="flex flex-col items-center gap-2 mb-2 z-10">
        {/* Video Scrubber Timeline (if video) */}
        {type === 'video' && (
          <div className="flex items-center gap-3 w-[450px] max-w-[90vw] rounded-xl bg-panel2/90 border border-line/80 px-4 py-2 shadow-2xl backdrop-blur-md text-xs font-mono">
            <button
              type="button"
              onClick={togglePlay}
              className="text-fg hover:text-brand transition cursor-pointer"
              title={isPlaying ? 'Pause (Space)' : 'Play (Space)'}
            >
              {isPlaying ? <Pause className="size-4" /> : <Play className="size-4 fill-current" />}
            </button>

            <span className="text-[11px] text-muted">{formatTime(currentTime)}</span>

            <input
              type="range"
              min={0}
              max={videoDuration || 100}
              step={0.1}
              value={currentTime}
              onChange={handleSeek}
              className="flex-1 h-1.5 bg-line rounded-lg appearance-none cursor-pointer accent-brand"
            />

            <span className="text-[11px] text-muted">{formatTime(videoDuration)}</span>

            <button
              type="button"
              onClick={toggleMute}
              className="text-muted hover:text-fg transition cursor-pointer"
              title={isMuted ? 'Unmute' : 'Mute'}
            >
              {isMuted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
            </button>

            <button
              type="button"
              onClick={cycleSpeed}
              className="px-1.5 py-0.5 rounded bg-panel border border-line text-[10px] font-semibold text-brand hover:border-brand transition cursor-pointer"
              title="Change Speed"
            >
              {playbackRate}x
            </button>

            <button
              type="button"
              onClick={() => setIsLooping(!isLooping)}
              className={`transition cursor-pointer ${isLooping ? 'text-brand' : 'text-muted hover:text-fg'}`}
              title="Toggle Loop"
            >
              <Repeat className="size-4" />
            </button>
          </div>
        )}

        {/* Zoom & Download Toolbar */}
        <div className="flex items-center gap-2 rounded-2xl bg-panel2/90 border border-line/80 px-4 py-2 shadow-2xl backdrop-blur-md">
          {/* Zoom Out */}
          <button
            type="button"
            onClick={handleZoomOut}
            disabled={scale <= 0.5}
            className="flex size-8 items-center justify-center rounded-lg hover:bg-panel text-muted hover:text-fg disabled:opacity-30 transition cursor-pointer"
            title="Zoom Out (-)"
          >
            <ZoomOut className="size-4" />
          </button>

          {/* Scale percentage */}
          <span className="min-w-[54px] text-center font-mono text-xs font-semibold text-fg">
            {Math.round(scale * 100)}%
          </span>

          {/* Zoom In */}
          <button
            type="button"
            onClick={handleZoomIn}
            disabled={scale >= 4}
            className="flex size-8 items-center justify-center rounded-lg hover:bg-panel text-muted hover:text-fg disabled:opacity-30 transition cursor-pointer"
            title="Zoom In (+)"
          >
            <ZoomIn className="size-4" />
          </button>

          <div className="h-4 w-px bg-line/60 mx-1" />

          {/* Reset (100%) */}
          <button
            type="button"
            onClick={handleReset}
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium text-muted hover:text-fg hover:bg-panel transition cursor-pointer"
            title="Reset Zoom & Pan (Ctrl+0)"
          >
            <RotateCcw className="size-3.5" />
            <span>100%</span>
          </button>

          {/* Fit */}
          <button
            type="button"
            onClick={() => {
              setScale(1)
              setPosition({ x: 0, y: 0 })
            }}
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium text-muted hover:text-fg hover:bg-panel transition cursor-pointer"
            title="Fit to screen"
          >
            <Maximize2 className="size-3.5" />
            <span>Fit</span>
          </button>

          <div className="h-4 w-px bg-line/60 mx-1" />

          {/* Download */}
          <button
            type="button"
            onClick={handleDownload}
            className="flex items-center gap-1.5 rounded-lg bg-brand hover:bg-brand/90 px-3 py-1.5 text-xs font-semibold text-brandfg transition cursor-pointer shadow-md"
            title="Download Media File"
          >
            <Download className="size-3.5" />
            <span>Download</span>
          </button>
        </div>
      </div>
    </div>
  )
}

// Backward-compatible alias
export const ImageLightboxModal = MediaLightboxModal
