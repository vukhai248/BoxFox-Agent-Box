/**
 * Trình xem ảnh tương tác (ImageLightboxModal).
 * - Thu phóng bằng con lăn chuột (Wheel Zoom từ 50% đến 400%).
 * - Kéo rê ảnh tự do (Pan & Drag khi di chuyển chuột).
 * - Thanh công cụ điều khiển nổi: Phóng to (+), Thu nhỏ (-), Tỷ lệ gốc (100%), Fit, Tải về (Download), Đóng (✕).
 * - Hỗ trợ phím tắt: ESC (đóng), Phím mũi tên (pan), Double-click (zoom toggle).
 * 
 * HƯỚNG DẪN SỬ DỤNG:
 * - Có thể tái sử dụng component này ở bất kỳ đâu trong ứng dụng khi cần xem ảnh chất lượng cao (ảnh chụp browser, biểu đồ AST, diagram kiến trúc...).
 * - Props: `src` (URL ảnh/Base64), `caption` (mô tả), `sourceUrl` (liên kết nguồn), `onClose` (callback đóng modal).
 */
import React, { useState, useRef, useEffect, useCallback } from 'react'
import {
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Maximize2,
  Download,
  X,
  ExternalLink,
} from 'lucide-react'

export interface LightboxImageProps {
  src: string
  alt?: string
  caption?: string
  sourceUrl?: string
  onClose: () => void
}

export function ImageLightboxModal({
  src,
  alt = 'Screenshot',
  caption,
  sourceUrl,
  onClose,
}: LightboxImageProps) {
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const containerRef = useRef<HTMLDivElement>(null)

  // Zoom controls
  const handleZoomIn = useCallback(() => {
    setZoom((z) => Math.min(4, Number((z + 0.25).toFixed(2))))
  }, [])

  const handleZoomOut = useCallback(() => {
    setZoom((z) => Math.max(0.5, Number((z - 0.25).toFixed(2))))
  }, [])

  const handleResetZoom = useCallback(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [])

  const handleFitScreen = useCallback(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [])

  // Mouse wheel zoom
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.deltaY < 0) {
      setZoom((z) => Math.min(4, Number((z + 0.15).toFixed(2))))
    } else {
      setZoom((z) => Math.max(0.5, Number((z - 0.15).toFixed(2))))
    }
  }

  // Pan & Drag handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return // Only primary click
    setIsDragging(true)
    dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y }
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return
    setPan({
      x: e.clientX - dragStart.current.x,
      y: e.clientY - dragStart.current.y,
    })
  }

  const handleMouseUp = () => {
    setIsDragging(false)
  }

  // Double click to toggle zoom
  const handleDoubleClick = () => {
    if (zoom === 1) {
      setZoom(2)
    } else {
      handleResetZoom()
    }
  }

  // Download image
  const handleDownload = () => {
    const link = document.createElement('a')
    link.href = src
    link.download = `boxfox-screenshot-${Date.now()}.png`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  // Keyboard navigation & ESC handler
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === '+' || e.key === '=') handleZoomIn()
      if (e.key === '-' || e.key === '_') handleZoomOut()
      if (e.key === '0') handleResetZoom()
      if (e.key === 'ArrowLeft') setPan((p) => ({ ...p, x: p.x + 30 }))
      if (e.key === 'ArrowRight') setPan((p) => ({ ...p, x: p.x - 30 }))
      if (e.key === 'ArrowUp') setPan((p) => ({ ...p, y: p.y + 30 }))
      if (e.key === 'ArrowDown') setPan((p) => ({ ...p, y: p.y - 30 }))
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose, handleZoomIn, handleZoomOut, handleResetZoom])

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-between bg-black/90 backdrop-blur-md animate-in fade-in duration-200 select-none"
      onMouseUp={handleMouseUp}
    >
      {/* Top Header Bar */}
      <div className="w-full flex items-center justify-between px-6 py-4 bg-gradient-to-b from-black/80 to-transparent z-10">
        <div className="flex items-center gap-3">
          <div className="flex size-7 items-center justify-center rounded-lg bg-white/10 text-white font-mono text-xs font-bold border border-white/15">
            IMG
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white truncate max-w-md">
              {caption || alt}
            </h3>
            {sourceUrl && (
              <a
                href={sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-white transition"
              >
                <span>{sourceUrl}</span>
                <ExternalLink className="size-3" />
              </a>
            )}
          </div>
        </div>

        {/* Close Button */}
        <button
          type="button"
          onClick={onClose}
          className="flex size-9 items-center justify-center rounded-xl bg-white/10 text-white/80 hover:bg-white/20 hover:text-white transition cursor-pointer border border-white/10"
          title="Close lightbox (Esc)"
        >
          <X className="size-5" />
        </button>
      </div>

      {/* Main Interactive Image Viewport */}
      <div
        ref={containerRef}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onDoubleClick={handleDoubleClick}
        className={`flex-1 w-full flex items-center justify-center overflow-hidden cursor-${
          zoom > 1 ? (isDragging ? 'grabbing' : 'grab') : 'default'
        } relative p-4`}
      >
        <div
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transition: isDragging ? 'none' : 'transform 0.12s ease-out',
          }}
          className="max-w-[90vw] max-h-[80vh] flex items-center justify-center"
        >
          <img
            src={src}
            alt={alt}
            draggable={false}
            className="rounded-xl shadow-2xl border border-white/15 object-contain max-h-[78vh] max-w-[88vw] select-none"
          />
        </div>
      </div>

      {/* Bottom Floating Control Bar */}
      <div className="w-full flex items-center justify-center pb-6 pt-2 z-10">
        <div className="flex items-center gap-1.5 rounded-2xl border border-white/15 bg-zinc-900/90 px-3 py-1.5 shadow-2xl backdrop-blur-md text-white text-xs">
          {/* Zoom Out Button */}
          <button
            type="button"
            onClick={handleZoomOut}
            className="flex size-8 items-center justify-center rounded-xl hover:bg-white/15 transition cursor-pointer text-white/80 hover:text-white"
            title="Zoom out (-)"
          >
            <ZoomOut className="size-4" />
          </button>

          {/* Zoom percentage badge */}
          <span className="font-mono text-[11px] px-2 font-semibold text-white/90 min-w-[50px] text-center">
            {Math.round(zoom * 100)}%
          </span>

          {/* Zoom In Button */}
          <button
            type="button"
            onClick={handleZoomIn}
            className="flex size-8 items-center justify-center rounded-xl hover:bg-white/15 transition cursor-pointer text-white/80 hover:text-white"
            title="Zoom in (+)"
          >
            <ZoomIn className="size-4" />
          </button>

          <div className="h-4 w-px bg-white/20 mx-1" />

          {/* Reset Zoom */}
          <button
            type="button"
            onClick={handleResetZoom}
            className="flex size-8 items-center justify-center rounded-xl hover:bg-white/15 transition cursor-pointer text-white/80 hover:text-white"
            title="Reset zoom (0)"
          >
            <RotateCcw className="size-3.5" />
          </button>

          {/* Fit to screen */}
          <button
            type="button"
            onClick={handleFitScreen}
            className="flex size-8 items-center justify-center rounded-xl hover:bg-white/15 transition cursor-pointer text-white/80 hover:text-white"
            title="Fit to window"
          >
            <Maximize2 className="size-3.5" />
          </button>

          <div className="h-4 w-px bg-white/20 mx-1" />

          {/* Download Image Button */}
          <button
            type="button"
            onClick={handleDownload}
            className="flex items-center gap-1.5 rounded-xl bg-white text-zinc-900 font-semibold px-3 py-1.5 hover:bg-zinc-100 transition cursor-pointer shadow-xs ml-1"
            title="Download image to computer"
          >
            <Download className="size-3.5" />
            <span className="text-[11px]">Download</span>
          </button>
        </div>
      </div>
    </div>
  )
}
