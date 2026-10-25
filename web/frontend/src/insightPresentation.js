export const DIMENSIONS = {
  hook: { label: '开场 Hook', tone: 'coral' },
  rhythm: { label: '节奏模式', tone: 'cyan' },
  shot_types: { label: '镜头类型', tone: 'violet' },
  emotion_arc: { label: '情绪弧线', tone: 'green' },
  transitions: { label: '转场使用', tone: 'violet' },
}

export const SHOT_LABELS = {
  hook: '开场 Hook', scene_establish: '场景建立', daily_moment: '日常叙事', persona_expression: '人物表达', emotion_peak: '情绪高潮', transition: '过渡', info_card: '信息卡', closing_moment: '收尾', cta: '行动引导', unknown: '未分类',
}

export const SHOT_COLORS = {
  hook: '#df9c88', scene_establish: '#84b8c1', daily_moment: '#a18bd4', persona_expression: '#bba1d1', emotion_peak: '#d9b874', transition: '#a0c8cd', info_card: '#91b9a3', closing_moment: '#aaa1b4', cta: '#d7a0ac', unknown: '#b8b0c2',
}

export const CONFIDENCE_LABEL = { high: '高置信', medium: '中置信', low: '样本不足' }
export const CONFIDENCE_BADGE = { high: 'green', medium: 'amber', low: 'gray' }

const TRANSITION_LABELS = { cut: '硬切', fade: '淡入淡出', dissolve: '叠化', none: '无转场', whip: '甩镜', mask: '遮罩', zoom_in: '推进', zoom_out: '拉远', flash_white: '白闪', blur_in: '模糊进入', occlusion_wipe: '遮挡擦除', cutout_outline: '抠图描边', subject_echo: '主体残影' }
export function metricLabel(value) { return SHOT_LABELS[value] || TRANSITION_LABELS[value] || value }
export function formatSeconds(value) { return value != null && Number.isFinite(Number(value)) && Number(value) >= 0 ? `${Number(value).toFixed(1)}s` : '—' }
export function sortedCounts(data) { return Object.entries(data || {}).map(([name, value]) => [name, Number(value)]).filter(([, value]) => Number.isFinite(value) && value > 0).sort((a, b) => b[1] - a[1]) }

export function insightCounter(insight) {
  const data = insight?.data || {}
  if (insight?.dimension === 'hook') return data.hook_methods || {}
  if (insight?.dimension === 'shot_types') return data.overall || {}
  if (insight?.dimension === 'emotion_arc') return data.overall_emotions || {}
  if (insight?.dimension === 'transitions') return Object.keys(data.from_packaging || {}).length ? data.from_packaging : data.from_shot_config || {}
  return {}
}

export function insightHeadline(insight) {
  const data = insight?.data || {}
  const [top] = sortedCounts(insightCounter(insight))
  if (insight?.dimension === 'hook' && Number.isFinite(data.avg_front_3s_shots)) return { value: data.avg_front_3s_shots.toFixed(1), unit: '镜 / 前 3 秒', note: top ? `主要方式 · ${metricLabel(top[0])}` : '暂无开场方式标注' }
  if (insight?.dimension === 'rhythm' && Number.isFinite(data.median_shot_duration)) return { value: data.median_shot_duration.toFixed(1), unit: '秒 / 镜头中位数', note: `时长范围 ${formatSeconds(data.min_shot_duration)}–${formatSeconds(data.max_shot_duration)}` }
  if (top) return { value: metricLabel(top[0]), unit: '', note: insight.dimension === 'shot_types' ? `${top[1]} 个镜头 · 共 ${data.total_shots || 0} 镜` : `${top[1]} 次记录 · 主要${insight.dimension === 'emotion_arc' ? '情绪' : '特征'}` }
  return { value: '暂无数据', unit: '', note: '等待更多有效分析' }
}

export function videoDisplayTitle(video) {
  const name = String(video?.name || '').replace(/\.[a-z0-9]{2,5}$/i, '')
  return /^[a-f\d]{24,}$/i.test(name) ? `${video.structure_type || '视频结构'}参考 · ${video.id.replace('video_', '#')}` : name || '未命名视频'
}
