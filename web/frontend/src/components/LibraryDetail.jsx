import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

export default function LibraryDetail({ title, subtitle, onClose, children, className = '', closeLabel = '关闭详情' }) {
  const ref = useRef(null)

  useEffect(() => {
    const dialog = ref.current
    dialog.showModal()
    return () => dialog.close()
  }, [])

  return (
    <dialog
      ref={ref}
      className={`vc-library-dialog ${className}`}
      aria-labelledby="library-detail-title"
      onCancel={(event) => { event.preventDefault(); onClose() }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return
        const rect = event.currentTarget.getBoundingClientRect()
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose()
      }}
    >
      <header className="vc-library-dialog-head">
        <div><small>{subtitle}</small><h2 id="library-detail-title">{title}</h2></div>
        <button type="button" onClick={onClose} aria-label={closeLabel} autoFocus><X size={19} /></button>
      </header>
      <div className="vc-library-dialog-body">{children}</div>
    </dialog>
  )
}
