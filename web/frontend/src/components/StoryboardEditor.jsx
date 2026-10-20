import { useEffect, useMemo, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Clock3,
  Image as ImageIcon,
  Layers3,
  Save,
  Trash2,
} from 'lucide-react'
import { confirmStoryboard, mediaUrl, updateStoryboard } from '../api.js'
import { Badge, Button, Card, Field, InfoBar, SelectInput, TextInput } from './ui.jsx'

const TRANSITIONS = [
  ['cut', '硬切'],
  ['fade', '淡入淡出'],
  ['dissolve', '叠化'],
  ['zoom_in', '推进'],
  ['zoom_out', '拉远'],
  ['slide_left', '左滑'],
  ['slide_right', '右滑'],
  ['wipe_left', '左擦除'],
  ['wipe_right', '右擦除'],
  ['blur_in', '模糊进入'],
  ['whip', '甩镜'],
  ['flash_white', '白闪'],
  ['circle_reveal', '圆形揭示'],
  ['glitch', '故障闪烁'],
  ['zoom_through', '穿越缩放'],
  ['liquid_warp', '液态形变'],
  ['chromatic_aberration', 'RGB 色差'],
  ['none', '无转场'],
]

function editableFrame(frame) {
  return {
    ...frame,
    material_id: frame.material_id || '',
    subtitle_text: frame.subtitle_text || '',
    transition: frame.transition || 'cut',
    duration: Number(frame.duration || 1),
  }
}

function MaterialPreview({ material, controls = false }) {
  const [failed, setFailed] = useState(false)
  if (!material || failed) {
    return <div className="vc-shot-placeholder"><ImageIcon size={24} /><span>{failed ? '素材预览暂不可用' : '尚未选择素材'}</span></div>
  }
  const isVideo = /\.(mp4|mov|webm|avi|mkv|m4v)$/i.test(material.filename || '')
  return isVideo ? (
    <video src={mediaUrl(material.preview_url)} controls={controls} muted={!controls} playsInline preload="metadata" onError={() => setFailed(true)} />
  ) : (
    <img src={mediaUrl(material.preview_url)} alt={material.filename} loading="lazy" onError={() => setFailed(true)} />
  )
}

export default function StoryboardEditor({ taskId, draft, onDraftChange, onConfirmed }) {
  const [title, setTitle] = useState(draft.title || '')
  const [frames, setFrames] = useState(() => draft.storyboard.map(editableFrame))
  const [saving, setSaving] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState(draft.storyboard[0]?.draft_id)

  useEffect(() => {
    setTitle(draft.title || '')
    setFrames(draft.storyboard.map(editableFrame))
  }, [draft])

  const materialMap = useMemo(
    () => new Map(draft.materials.map((material) => [String(material.id), material])),
    [draft.materials]
  )
  const totalDuration = frames.reduce((sum, frame) => sum + Number(frame.duration || 0), 0)
  const selectedIndex = Math.max(0, frames.findIndex((frame) => frame.draft_id === selectedId))
  const selectedFrame = frames[selectedIndex]
  const selectedMaterial = materialMap.get(String(selectedFrame?.material_id))
  const busy = saving || confirming
  const shotStart = frames.slice(0, selectedIndex).reduce((sum, frame) => sum + Number(frame.duration || 0), 0)

  const updateFrame = (index, patch) => {
    setFrames((current) => current.map((frame, i) => (i === index ? { ...frame, ...patch } : frame)))
    setMessage('')
  }

  const moveFrame = (index, offset) => {
    const target = index + offset
    if (target < 0 || target >= frames.length) return
    setFrames((current) => {
      const next = [...current]
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
    setMessage('')
  }

  const removeFrame = (index) => {
    if (frames.length <= 1) return
    setFrames((current) => current.filter((_, i) => i !== index))
    setMessage('')
  }

  const payload = () => ({
    title,
    revision: draft.revision,
    storyboard: frames.map((frame) => ({
      draft_id: frame.draft_id,
      material_id: frame.material_id,
      duration: Number(frame.duration),
      subtitle_text: frame.subtitle_text,
      transition: frame.transition,
    })),
  })

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      const response = await updateStoryboard(taskId, payload())
      onDraftChange(response.data)
      setMessage(`第 ${response.data.revision} 版已保存`)
      return response.data
    } catch (err) {
      setError(err.response?.data?.detail || '保存分镜失败')
      return null
    } finally {
      setSaving(false)
    }
  }

  const confirm = async () => {
    setConfirming(true)
    setError('')
    try {
      const saved = await save()
      if (!saved) return
      const response = await confirmStoryboard(taskId)
      onConfirmed(response.data)
    } catch (err) {
      setError(err.response?.data?.detail || '提交渲染失败')
    } finally {
      setConfirming(false)
    }
  }

  return (
    <Card className="vc-storyboard mb-6 overflow-hidden">
      <div className="vc-studio-toolbar">
        <div className="vc-studio-title"><span><Layers3 size={18} /></span><div><small>STORYBOARD STUDIO</small><h2>分镜确认台</h2></div></div>
        <div className="vc-studio-meta"><Badge color="amber">等待确认</Badge><span>第 {draft.revision} 版</span><span><Clock3 size={13} />{frames.length} 镜头 · {totalDuration.toFixed(1)}s</span></div>
      </div>

      <div className="vc-studio-workspace">
        <aside className="vc-shot-list" aria-label="分镜列表">
          <div className="vc-studio-panel-head"><strong>镜头序列</strong><span>{frames.length}</span></div>
          <div className="vc-shot-list-scroll">
            {frames.map((frame, index) => (
              <button type="button" key={frame.draft_id} aria-pressed={index === selectedIndex} onClick={() => setSelectedId(frame.draft_id)} className={`vc-shot-item ${index === selectedIndex ? 'is-selected' : ''}`}>
                <span className="vc-shot-thumb"><MaterialPreview key={frame.material_id} material={materialMap.get(String(frame.material_id))} /></span>
                <span className="vc-shot-item-copy"><strong>镜头 {String(index + 1).padStart(2, '0')}</strong><small>{Number(frame.duration).toFixed(1)}s · {TRANSITIONS.find(([value]) => value === frame.transition)?.[1] || frame.transition}</small></span>
              </button>
            ))}
          </div>
        </aside>

        <section className="vc-shot-canvas" aria-label="当前分镜预览">
          <div className="vc-canvas-caption"><span>素材预览</span><span>{selectedFrame ? `镜头 ${String(selectedIndex + 1).padStart(2, '0')}` : '暂无分镜'}</span></div>
          <div className="vc-shot-stage">
            <div className="vc-shot-screen"><MaterialPreview key={selectedFrame?.material_id} material={selectedMaterial} controls /></div>
            <p>预览原始素材；字幕、转场与动效会在确认渲染后呈现。</p>
          </div>
          <div className="vc-shot-timecode"><Clock3 size={12} /><span>{shotStart.toFixed(1)}s — {(shotStart + Number(selectedFrame?.duration || 0)).toFixed(1)}s</span><span>共 {totalDuration.toFixed(1)}s</span></div>
        </section>

        <aside className="vc-shot-inspector" aria-label="分镜属性">
          <div className="vc-studio-panel-head"><strong>镜头属性</strong><span>{String(selectedIndex + 1).padStart(2, '0')}</span></div>
          {selectedFrame && (
            <fieldset disabled={busy} className="vc-inspector-fields">
              <Field label="使用素材"><SelectInput aria-label="使用素材" value={selectedFrame.material_id} onChange={(event) => updateFrame(selectedIndex, { material_id: event.target.value })}>
                <option value="">不使用素材</option>
                {draft.materials.map((item) => <option key={item.id} value={item.id}>{item.description || item.filename || item.id}</option>)}
              </SelectInput></Field>
              <Field label="字幕"><TextInput aria-label="字幕" value={selectedFrame.subtitle_text} maxLength={200} placeholder="该镜头不显示字幕" onChange={(event) => updateFrame(selectedIndex, { subtitle_text: event.target.value })} /></Field>
              <Field label="时长（秒）"><TextInput aria-label="时长（秒）" type="number" min="0.2" max="30" step="0.1" value={selectedFrame.duration} onChange={(event) => updateFrame(selectedIndex, { duration: event.target.value })} /></Field>
              <Field label="转场"><SelectInput aria-label="转场" value={selectedFrame.transition} onChange={(event) => updateFrame(selectedIndex, { transition: event.target.value })}>
                {!TRANSITIONS.some(([value]) => value === selectedFrame.transition) && <option value={selectedFrame.transition}>{selectedFrame.transition}</option>}
                {TRANSITIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </SelectInput></Field>
              {selectedFrame.render_component && selectedFrame.render_component !== 'auto' && (
                <div className="vc-shot-effect"><Badge color="purple">高级动效</Badge><span>{selectedFrame.render_component.replace(/^custom:/, '')}</span></div>
              )}
              <div className="vc-shot-actions">
                <Button variant="secondary" size="sm" icon={ArrowUp} disabled={selectedIndex === 0} aria-label="上移分镜" onClick={() => moveFrame(selectedIndex, -1)}>上移</Button>
                <Button variant="secondary" size="sm" icon={ArrowDown} disabled={selectedIndex === frames.length - 1} aria-label="下移分镜" onClick={() => moveFrame(selectedIndex, 1)}>下移</Button>
                <Button variant="danger" size="sm" icon={Trash2} disabled={frames.length <= 1} aria-label="删除分镜" onClick={() => removeFrame(selectedIndex)}>删除</Button>
              </div>
            </fieldset>
          )}
        </aside>
      </div>

      <div className="vc-studio-footer">
        <Field label="作品标题" className="vc-studio-title-field"><TextInput aria-label="作品标题" disabled={busy} value={title} maxLength={120} onChange={(event) => { setTitle(event.target.value); setMessage('') }} /></Field>
        <div className="vc-studio-save-actions">
          <Button variant="secondary" icon={Save} loading={saving} disabled={confirming || !frames.length} onClick={save}>保存草案</Button>
          <Button icon={CheckCircle2} loading={confirming} disabled={saving || !frames.length} onClick={confirm}>确认并开始渲染</Button>
        </div>
      </div>
      {(error || message) && <div className="vc-studio-feedback" role="status"><InfoBar type={error ? 'error' : 'success'}>{error || message}</InfoBar></div>}
    </Card>
  )
}
