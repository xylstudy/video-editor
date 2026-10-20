import { insightCounter, metricLabel, sortedCounts } from '../insightPresentation.js'
import { compactText } from '../library.js'

export default function InsightGraphic({ insight }) {
  const rhythm = insight.dimension === 'rhythm'
  const data = insight.data || {}
  const entries = rhythm
    ? [['前段均值', data.first_third_avg], ['中位时长', data.median_shot_duration], ['后段均值', data.last_third_avg]].filter(([, value]) => Number.isFinite(value) && value > 0)
    : sortedCounts(insightCounter(insight)).slice(0, 4)
  const max = Math.max(1, ...entries.map(([, value]) => Number(value)))
  return (
    <div className={`vc-insight-graphic ${rhythm ? 'is-rhythm' : ''}`} role="img" aria-label={entries.length ? entries.map(([label, value]) => `${metricLabel(label)} ${value}${rhythm ? ' 秒' : ' 次'}`).join('、') : '暂无有效统计数据'}>
      {entries.length ? <div className="vc-insight-mini-bars">{entries.map(([name, value]) => <span key={name} title={`${metricLabel(name)} · ${value}${rhythm ? 's' : ''}`}><i style={{ height: `${Math.max(2, (Number(value) / max) * 44)}px` }} /><small>{compactText(metricLabel(name), 6)}</small></span>)}</div> : <span className="vc-insight-no-data">等待样本</span>}
    </div>
  )
}
