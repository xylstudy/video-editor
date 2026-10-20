import { ArrowRight, Clapperboard, Heart, Layers3, Music2, Palette, Scissors, Sparkles, Zap } from 'lucide-react'
import { compactText } from '../library.js'

const KNOWLEDGE_ICONS = {
  transition_type: ArrowRight,
  editing_technique: Scissors,
  packaging_style: Palette,
  effect_type: Sparkles,
  structure_template: Layers3,
  hook_technique: Zap,
  rhythm_pattern: Music2,
  emotion_design: Heart,
}

export default function KnowledgeVisual({ entry }) {
  const data = entry.structured_data || {}
  const Icon = KNOWLEDGE_ICONS[entry.type] || Clapperboard
  const segments = Array.isArray(data.script_structure) ? data.script_structure : []
  const rawPoints = data.rhythm_analysis?.curve_points
  const points = (Array.isArray(rawPoints) ? rawPoints : []).filter((point) => Number.isFinite(Number(point.intensity)))
  const emotions = Object.entries(data.emotion_distribution || {}).filter(([, count]) => Number.isFinite(Number(count)) && Number(count) > 0).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 4)

  if (entry.type === 'structure_template' && segments.length) {
    return (
      <div className="vc-knowledge-visual is-structure" role="img" aria-label={`段落结构：${segments.map((segment) => segment.purpose).join('、')}`}>
        <span className="vc-visual-caption">段落结构</span>
        <div className="vc-structure-strip">{segments.map((segment, index) => <span key={index} style={{ flexGrow: Number(segment.duration_hint) > 0 ? Number(segment.duration_hint) : 1 }} title={`${segment.purpose} · ${segment.duration_hint || '—'}s`}><i /><small>{compactText(segment.purpose, 5)}</small></span>)}</div>
      </div>
    )
  }
  if (entry.type === 'rhythm_pattern' && points.length > 1) {
    const maxTime = Math.max(1, ...points.map((point) => Number(point.time) || 0))
    const coords = points.map((point) => `${8 + ((Number(point.time) || 0) / maxTime) * 264},${57 - Math.min(1, Math.max(0, Number(point.intensity))) * 40}`).join(' ')
    return (
      <div className="vc-knowledge-visual is-rhythm" role="img" aria-label={`节奏强度曲线，${points.length} 个采样点`}>
        <span className="vc-visual-caption">节奏强度</span>
        <svg viewBox="0 0 280 70" aria-hidden="true"><path d="M8 57H272M8 37H272" stroke="currentColor" opacity=".12" /><polygon points={`8,64 ${coords} 272,64`} fill="currentColor" opacity=".1" /><polyline points={coords} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" /></svg>
      </div>
    )
  }
  if (entry.type === 'emotion_design' && emotions.length) {
    const total = emotions.reduce((sum, [, count]) => sum + Number(count), 0)
    return (
      <div className="vc-knowledge-visual is-emotion" role="img" aria-label={`主要情绪：${emotions.map(([name, count]) => `${name} ${count}`).join('、')}`}>
        <span className="vc-visual-caption">主要情绪</span>
        <div className="vc-emotion-strip">{emotions.map(([name, count]) => <span key={name} style={{ flexGrow: Number(count) / total }}><i /><small>{compactText(name, 5)}</small></span>)}</div>
      </div>
    )
  }
  return <div className={`vc-knowledge-visual is-${entry.type}`} aria-hidden="true"><span className="vc-visual-frame" /><span className="vc-visual-icon"><Icon size={25} strokeWidth={1.5} /></span><span className="vc-visual-frame is-right" /></div>
}
