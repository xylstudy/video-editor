import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, BarChart3, Clock3, Database, Film, Image as ImageIcon, RefreshCw, Search, Sparkles } from 'lucide-react'
import api, { mediaUrl } from '../api.js'
import { Badge, Button, Card, EmptyState, InfoBar, SectionHeader, SelectInput, TextInput } from '../components/ui.jsx'
import LibraryDetail from '../components/LibraryDetail.jsx'
import MediaCover from '../components/MediaCover.jsx'
import InsightGraphic from '../components/InsightGraphic.jsx'
import { compactText, firstSentence } from '../library.js'
import { CONFIDENCE_BADGE, CONFIDENCE_LABEL, DIMENSIONS, SHOT_COLORS, SHOT_LABELS, formatSeconds, insightCounter, insightHeadline, metricLabel, sortedCounts, videoDisplayTitle } from '../insightPresentation.js'

function MetricCard({ icon: Icon, label, value, hint, tone }) {
  return <Card className="vc-insight-metric"><span className={`vc-metric-icon tone-${tone}`}><Icon size={18} /></span><div><small>{label}</small><strong>{value}</strong><p>{hint}</p></div></Card>
}

function Distribution({ data, rhythm = false }) {
  const entries = sortedCounts(data)
  const max = Math.max(1, ...entries.map(([, value]) => value))
  const total = entries.reduce((sum, [, value]) => sum + value, 0)
  if (!entries.length) return <p className="vc-insight-empty-data">暂无有效统计数据</p>
  return <div className="vc-insight-distribution">{entries.map(([name, value]) => <div key={name}><span title={metricLabel(name)}>{metricLabel(name)}</span><small>{value}{rhythm ? 's' : ` · ${Math.round((value / total) * 100)}%`}</small><i><b style={{ width: `${(value / max) * 100}%` }} /></i></div>)}</div>
}

function ShotTimeline({ video, selected, onSelect }) {
  if (!video?.shots?.length) return <p className="vc-insight-empty-data">暂无镜头时间数据</p>
  return <>
    <div className="vc-insight-timeline-scroll"><div className="vc-insight-timeline" style={{ minWidth: `${Math.max(280, video.shots.length * 24)}px` }}>{video.shots.map((shot) => <button type="button" key={shot.index} aria-pressed={selected === shot.index} aria-label={`查看镜头 ${shot.index + 1}`} title={`镜头 ${shot.index + 1} · ${SHOT_LABELS[shot.shot_type] || shot.shot_type} · ${formatSeconds(shot.duration)}`} onClick={() => onSelect(shot.index)} style={{ flexGrow: Math.max(Number(shot.duration) || 0, .1), background: SHOT_COLORS[shot.shot_type] || SHOT_COLORS.unknown }} className={selected === shot.index ? 'is-selected' : ''}>{shot.index + 1}</button>)}</div></div>
    <div className="vc-insight-timeline-legend">{[...new Set(video.shots.map((shot) => shot.shot_type))].map((type) => <span key={type}><i style={{ background: SHOT_COLORS[type] || SHOT_COLORS.unknown }} />{SHOT_LABELS[type] || type}</span>)}</div>
  </>
}

export default function Insights() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [viewMode, setViewMode] = useState('library')
  const [selectedVideoId, setSelectedVideoId] = useState('')
  const [selectedShotIndex, setSelectedShotIndex] = useState(0)
  const [query, setQuery] = useState('')
  const [structure, setStructure] = useState('')
  const [detail, setDetail] = useState(null)
  const requestId = useRef(0)

  const load = useCallback(async () => {
    const request = ++requestId.current
    setLoading(true)
    setError('')
    setDetail(null)
    try {
      const response = await api.get('/insights')
      if (request !== requestId.current) return
      setData(response.data)
      setSelectedVideoId((current) => response.data.videos?.some((video) => video.id === current) ? current : response.data.videos?.[0]?.id || '')
    } catch (err) {
      if (request === requestId.current) setError(err.response?.data?.detail || '洞察数据加载失败，请稍后重试')
    } finally {
      if (request === requestId.current) setLoading(false)
    }
  }, [])

  useEffect(() => { load(); return () => { requestId.current += 1 } }, [load])

  const videos = data?.videos || []
  const selectedVideo = useMemo(() => data?.videos?.find((video) => video.id === selectedVideoId) || data?.videos?.[0], [data, selectedVideoId])
  const singleReport = data?.video_reports?.find((report) => report.video_id === selectedVideo?.id)
  const isSingle = viewMode === 'video'
  // Missing single-video statistics must never inherit pooled aggregate counters.
  const report = isSingle ? singleReport : data
  const reportVideos = isSingle ? (selectedVideo ? [selectedVideo] : []) : videos
  const totalShots = reportVideos.reduce((sum, video) => sum + Number(video.shot_count || 0), 0)
  const timedVideos = reportVideos.filter((video) => Number(video.duration) > 0)
  const averageDuration = timedVideos.length ? timedVideos.reduce((sum, video) => sum + Number(video.duration), 0) / timedVideos.length : 0
  const selectedShot = selectedVideo?.shots?.find((shot) => shot.index === selectedShotIndex) || selectedVideo?.shots?.[0]
  const keyword = query.trim().toLowerCase()
  const filteredVideos = videos.filter((video) => (!structure || video.structure_type === structure) && (!keyword || [video.name, video.structure_type, video.hook_method, video.overall_emotion].some((value) => String(value || '').toLowerCase().includes(keyword))))
  const openVideo = (id) => { setSelectedVideoId(id); setSelectedShotIndex(0); setViewMode('video') }
  const selectedInsight = detail?.insight
  const rhythmData = selectedInsight?.data || {}
  const detailCounts = selectedInsight?.dimension === 'rhythm' ? { '平均镜头时长': rhythmData.avg_shot_duration, '镜头时长中位数': rhythmData.median_shot_duration, '前段均值': rhythmData.first_third_avg, '后段均值': rhythmData.last_third_avg } : insightCounter(selectedInsight)

  return (
    <div>
      <SectionHeader title="统计洞察" description="浏览视频特征，用图形摘要查看结构规律与镜头依据" actions={<Button variant="secondary" icon={RefreshCw} loading={loading} onClick={load}>刷新统计</Button>} />
      {error && <div className="mb-4"><InfoBar type="error">{error}<button type="button" className="ml-3 underline" onClick={load}>重试</button></InfoBar></div>}
      {loading && !data ? <div className="py-16 text-center text-sm text-[#8b8495]">正在整理分析报告…</div> : !data ? null : !data.sample_size ? <Card><EmptyState icon={BarChart3} title="还没有个人洞察" description="先完成一个视频基因分析，即可查看对应的结构特征"><Link className="vc-library-source-link" to="/genes">前往基因库 <ArrowUpRight size={14} /></Link></EmptyState></Card> : <>
        <div className="vc-insight-view-toolbar"><div className="vc-library-filters" aria-label="洞察视图"><button type="button" className={viewMode === 'library' ? 'is-active' : ''} aria-pressed={viewMode === 'library'} onClick={() => setViewMode('library')}>视频特征库</button><button type="button" className={viewMode === 'aggregate' ? 'is-active' : ''} aria-pressed={viewMode === 'aggregate'} onClick={() => setViewMode('aggregate')}>综合统计</button>{isSingle && <span className="vc-insight-current-view">单视频报告</span>}</div><span className="vc-insight-updated">更新于 {data.generated_at ? new Date(data.generated_at).toLocaleString('zh-CN') : '—'}</span></div>

        <div className="vc-insight-metric-grid">
          <MetricCard icon={Database} label={isSingle ? '当前样本' : '统计样本'} value={isSingle ? (selectedVideo ? 1 : 0) : data.sample_size} hint="当前账号的分析报告" tone="violet" />
          <MetricCard icon={Film} label="镜头总数" value={totalShots} hint={isSingle ? '当前视频' : '统计范围内的全部镜头'} tone="cyan" />
          <MetricCard icon={Clock3} label={isSingle ? '视频时长' : '平均视频时长'} value={formatSeconds(averageDuration)} hint={`${timedVideos.length} 个有效时长样本`} tone="coral" />
          <MetricCard icon={BarChart3} label="分析维度" value={report?.insights?.length || 0} hint="开场 · 节奏 · 镜头 · 情绪 · 转场" tone="green" />
        </div>

        {viewMode === 'library' ? <>
          <div className="vc-library-toolbar"><div className="vc-insight-library-heading"><h2>已分析视频</h2><span>{filteredVideos.length} 个参考</span></div><div className="vc-insight-library-filters"><SelectInput value={structure} onChange={(event) => setStructure(event.target.value)} aria-label="筛选洞察结构"><option value="">全部结构</option>{[...new Set(videos.map((video) => video.structure_type).filter(Boolean))].map((type) => <option key={type} value={type}>{compactText(type, 24)}</option>)}</SelectInput><div className="vc-library-search"><Search size={15} /><TextInput value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索视频 / 特征 / 情绪" aria-label="搜索洞察视频" /></div></div></div>
          {!filteredVideos.length ? <Card><EmptyState icon={Search} title="没有匹配的视频" description="换个关键词或结构类型试试" /></Card> : <div className="vc-gene-grid">
            {filteredVideos.map((video) => <Card hover key={video.id} className="vc-insight-video-card"><button type="button" onClick={() => openVideo(video.id)} aria-label={`查看独立洞察：${video.id}`}>
              <MediaCover imageSrc={video.cover_available ? mediaUrl(`/insights/videos/${video.id}/cover`) : undefined} videoSrc={video.media_available ? mediaUrl(`/insights/videos/${video.id}/media`) : undefined} alt={`${videoDisplayTitle(video)}关键帧`}><span className="vc-work-cover-badge"><Badge color="green">已分析</Badge></span><span className="vc-work-cover-id">{video.id.replace('video_', 'VIDEO ')}</span></MediaCover>
              <span className="vc-insight-video-body"><strong title={video.name}>{compactText(videoDisplayTitle(video), 42)}</strong><span className="vc-gene-metrics"><span><strong>{Number(video.duration || 0).toFixed(1)}</strong>秒</span><span><strong>{video.shot_count}</strong>镜头</span><span><strong>{video.front_3s_shot_count ?? '—'}</strong>前 3 秒镜头</span></span><span className="vc-insight-video-tags"><Badge color="indigo">{compactText(video.structure_type || '未标注结构', 14)}</Badge><small title={video.overall_emotion}>{compactText(video.overall_emotion || '未标注情绪', 14)}</small></span><span className="vc-insight-video-footer">查看独立洞察 <ArrowUpRight size={13} /></span></span>
            </button></Card>)}
          </div>}
        </> : <>
          {isSingle && selectedVideo && <div className="vc-insight-report-scope"><div><small>当前独立报告</small><h2>{videoDisplayTitle(selectedVideo)}</h2></div><SelectInput aria-label="选择独立洞察视频" value={selectedVideo.id} onChange={(event) => openVideo(event.target.value)}>{videos.map((video) => <option key={video.id} value={video.id}>{compactText(videoDisplayTitle(video), 36)}</option>)}</SelectInput></div>}
          {viewMode === 'aggregate' && data.sample_size === 1 && <div className="mb-4"><InfoBar type="warn">当前仅有 1 个样本，展示的是单视频特征；积累更多参考后再比较跨视频规律。</InfoBar></div>}
          {isSingle && !singleReport && <div className="mb-4"><InfoBar type="info">该视频缺少独立统计，仍可查看下方逐镜头依据。</InfoBar></div>}
          <div className="vc-insight-dimension-grid">
            {(report?.insights || []).map((insight) => {
              const headline = insightHeadline(insight)
              const meta = DIMENSIONS[insight.dimension] || { label: insight.dimension, tone: 'violet' }
              return <Card hover key={insight.dimension} className={`vc-insight-dimension-card tone-${meta.tone}`}><button type="button" onClick={() => setDetail({ kind: 'dimension', insight, scope: isSingle ? videoDisplayTitle(selectedVideo) : '综合统计' })} aria-label={`查看${meta.label}完整统计`}><InsightGraphic insight={insight} /><span className="vc-insight-dimension-body"><span className="vc-insight-dimension-title"><strong>{meta.label}</strong><Badge color={CONFIDENCE_BADGE[insight.confidence] || 'gray'}>{CONFIDENCE_LABEL[insight.confidence] || '未标注'}</Badge></span><span className="vc-insight-headline" title={headline.value}>{compactText(headline.value, 18)}<small>{headline.unit}</small></span><span className="vc-insight-dimension-note">{compactText(headline.note, 40)}</span><span className="vc-insight-dimension-footer"><small>有效样本 n={insight.sample_size ?? 0}</small><span>查看依据 <ArrowUpRight size={13} /></span></span></span></button></Card>
            })}
          </div>

          <Card className="vc-insight-explorer-card"><details key={viewMode} open={isSingle}><summary><span><Sparkles size={16} />逐镜头依据</span><small>选择色块查看镜头</small></summary><div className="vc-insight-explorer-body">
            <div className="vc-insight-explorer-select"><span>镜头来源</span><SelectInput aria-label="选择镜头来源" value={selectedVideo?.id || ''} onChange={(event) => { setSelectedVideoId(event.target.value); setSelectedShotIndex(0) }}>{videos.map((video) => <option key={video.id} value={video.id}>{compactText(videoDisplayTitle(video), 40)}</option>)}</SelectInput></div>
            <ShotTimeline video={selectedVideo} selected={selectedShot?.index} onSelect={setSelectedShotIndex} />
            {selectedShot ? <div className="vc-insight-shot-preview"><span className="vc-insight-shot-number">{String(selectedShot.index + 1).padStart(2, '0')}</span><div><strong>{SHOT_LABELS[selectedShot.shot_type] || selectedShot.shot_type}</strong><small>{formatSeconds(selectedShot.start)}–{formatSeconds(selectedShot.end)} · {selectedShot.emotion || '未标注情绪'}</small><p>{firstSentence(selectedShot.detail?.summary || selectedShot.detail?.visual || '该历史镜头没有保存画面摘要。', 100)}</p></div><button type="button" className="vc-library-detail-button" onClick={() => setDetail({ kind: 'shot', shot: selectedShot, video: selectedVideo })}>完整依据 <ArrowUpRight size={13} /></button></div> : <p className="vc-insight-empty-data">暂无可用镜头</p>}
            {!!selectedVideo?.shots?.some((shot) => shot.emotion) && <details className="vc-insight-emotion-flow"><summary>查看完整情绪流</summary><div>{selectedVideo.shots.filter((shot) => shot.emotion).map((shot) => <span key={shot.index}>{shot.emotion}</span>)}</div></details>}
          </div></details></Card>
        </>}
      </>}

      {detail?.kind === 'dimension' && <LibraryDetail title={`${DIMENSIONS[selectedInsight.dimension]?.label || selectedInsight.dimension}统计`} subtitle={detail.scope} closeLabel="关闭洞察详情" onClose={() => setDetail(null)}>
        <InsightGraphic insight={selectedInsight} />
        <section className="vc-knowledge-detail-section"><h3>完整统计结论</h3><p>{selectedInsight.finding || '暂无结论'}</p></section>
        <section className="vc-knowledge-detail-section"><h3>{selectedInsight.dimension === 'rhythm' ? '时长指标' : '特征分布'}</h3><Distribution data={detailCounts} rhythm={selectedInsight.dimension === 'rhythm'} /></section>
        <section className="vc-knowledge-detail-section"><h3>样本范围</h3><p>{detail.scope} · 有效样本 {selectedInsight.sample_size ?? 0} · {CONFIDENCE_LABEL[selectedInsight.confidence] || '置信度未标注'}</p>{selectedInsight.dimension === 'transitions' && <p>{Object.keys(selectedInsight.data?.from_packaging || {}).length ? '计数来源：各视频包装分析中的转场记录。' : '计数来源：逐镜头转场配置。'}</p>}</section>
      </LibraryDetail>}
      {detail?.kind === 'shot' && <LibraryDetail title={`镜头 ${detail.shot.index + 1} · ${SHOT_LABELS[detail.shot.shot_type] || detail.shot.shot_type}`} subtitle={videoDisplayTitle(detail.video)} closeLabel="关闭镜头依据" onClose={() => setDetail(null)}>
        {detail.video.media_available ? <video className="vc-insight-source-video" key={detail.video.id} src={mediaUrl(`/insights/videos/${detail.video.id}/media`)} controls playsInline preload="metadata" aria-label="镜头来源视频" onLoadedMetadata={(event) => { const video = event.currentTarget; if (Number.isFinite(video.duration) && video.duration > 0) video.currentTime = Math.max(0, Math.min(Number(detail.shot.start) || 0, video.duration - .05)) }} /> : <div className="vc-insight-source-missing"><ImageIcon size={24} /><p>源文件暂不可用，以下保留该镜头的分析记录。</p></div>}
        <section className="vc-knowledge-detail-section"><h3>时间与标注</h3><p>{formatSeconds(detail.shot.start)}–{formatSeconds(detail.shot.end)} · 时长 {formatSeconds(detail.shot.duration)}<br />情绪：{detail.shot.emotion || '未标注'} · 转场：{metricLabel(detail.shot.transition || 'none')}</p></section>
        <section className="vc-knowledge-detail-section"><h3>画面摘要</h3><p>{detail.shot.detail?.summary || detail.shot.detail?.visual || '该历史镜头未保存摘要。'}</p></section>
        {detail.shot.detail?.reasoning && <section className="vc-knowledge-detail-section"><h3>结构判断依据</h3><p>{detail.shot.detail.reasoning}</p></section>}
        <details className="vc-library-extra"><summary>分析记录</summary><p className="vc-insight-trace">{detail.shot.detail?.has_trace ? `${detail.shot.detail.prompt_version || '分析轨迹'} · ${detail.shot.detail.model || '模型未记录'}` : '历史数据未保存完整推理轨迹'}</p></details>
      </LibraryDetail>}
    </div>
  )
}
