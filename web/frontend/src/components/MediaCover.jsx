import { useEffect, useRef, useState } from 'react'
import { Film } from 'lucide-react'

const posterCache = new Map()

// Capture one frame near the start, then release the decoder. Cards never play video.
export default function MediaCover({ imageSrc, videoSrc, alt, children, className = '' }) {
  const ref = useRef(null)
  const [visible, setVisible] = useState(false)
  const [imageFailed, setImageFailed] = useState(false)
  const [poster, setPoster] = useState(() => posterCache.get(videoSrc) || '')

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setVisible(true); observer.disconnect() }
    }, { rootMargin: '120px' })
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!visible || (imageSrc && !imageFailed) || !videoSrc || poster) return
    let stopped = false
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.preload = 'metadata'
    const release = () => {
      video.onloadedmetadata = null
      video.onseeked = null
      video.onerror = null
      video.removeAttribute('src')
      video.load()
    }
    const timeout = window.setTimeout(release, 10000)
    video.onloadedmetadata = () => {
      if (Number.isFinite(video.duration) && video.duration > 0) video.currentTime = Math.min(.3, video.duration / 2)
      else { window.clearTimeout(timeout); release() }
    }
    video.onseeked = () => {
      try {
        if (stopped || !video.videoWidth || !video.videoHeight) return
        const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight))
        const canvas = document.createElement('canvas')
        canvas.width = Math.max(1, Math.round(video.videoWidth * scale))
        canvas.height = Math.max(1, Math.round(video.videoHeight * scale))
        const context = canvas.getContext('2d')
        if (!context) return
        context.drawImage(video, 0, 0, canvas.width, canvas.height)
        const captured = canvas.toDataURL('image/jpeg', .8)
        if (posterCache.size >= 48) posterCache.delete(posterCache.keys().next().value)
        posterCache.set(videoSrc, captured)
        setPoster(captured)
      } catch {
        // A failed cover does not prevent opening the full video in the detail view.
      } finally {
        window.clearTimeout(timeout)
        release()
      }
    }
    video.onerror = () => { window.clearTimeout(timeout); release() }
    video.src = videoSrc
    return () => { stopped = true; window.clearTimeout(timeout); release() }
  }, [visible, imageSrc, imageFailed, videoSrc, poster])

  const source = imageSrc && !imageFailed ? imageSrc : poster
  return (
    <div ref={ref} className={`vc-media-cover ${className}`}>
      {source ? <img src={source} alt={alt} loading="lazy" onError={() => setImageFailed(true)} /> : <span className="vc-media-cover-fallback" aria-label={alt}><Film size={29} strokeWidth={1.25} /><small>视频预览</small></span>}
      {children}
    </div>
  )
}
