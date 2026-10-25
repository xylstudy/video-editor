import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  Clapperboard,
  Dna,
  Loader2,
  Music,
  Scissors,
  Sparkles,
  Terminal,
  Trash2,
  Zap,
} from 'lucide-react'
import { deleteGene, extractGeneKnowledge, getGene, mediaUrl } from '../api.js'
import { compactText, geneDisplayTitle, shortHeading } from '../library.js'
import {
  Badge,
  Button,
  Card,
  InfoBar,
  ProgressBar,
  SectionHeader,
} from '../components/ui.jsx'

const PURPOSE_COLORS = {
  hook: 'red',
  人设展示: 'purple',
  场景铺展: 'blue',
  情绪递进: 'indigo',
  高潮爆发: 'amber',
  价值输出: 'green',
  CTA互动: 'blue',
}

function SectionTitle({ icon: Icon, children }) {
  return (
    <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
      <Icon size={16} className="text-[#b49aff]" />
      {children}
    </h2>
  )
}

function ReportRow({ label, children }) {
  const text = Array.isArray(children) ? children.filter((item) => item != null && item !== false).join('') : children
  return (
    <div className="vc-report-row">
      <span>{label}</span>
      <ReportText text={text || '—'} />
    </div>
  )
}

function ReportText({ text, limit = 110 }) {
  const value = String(text || '')
  if (value.length <= limit) return <p className="vc-report-text">{value || '—'}</p>
  return <details className="vc-report-readmore"><summary><span className="vc-report-excerpt">{compactText(value, limit)}</span><span className="vc-report-expand">展开全文</span><span className="vc-report-collapse">收起全文</span></summary><p className="vc-report-text">{value}</p></details>
}

/* 节奏曲线（纯 CSS 柱状图） */
function RhythmChart({ points = [] }) {
  if (!points.length) return null
  return (
    <div className="flex items-end gap-1.5 overflow-x-auto pb-2" style={{ height: 120 }}>
      {points.map((p, i) => (
        <div key={i} className="group flex min-w-[34px] flex-1 flex-col items-center justify-end">
          <div className="relative w-full">
            <div
              className="w-full rounded-t bg-gradient-to-t from-[#7c5cfc] to-[#00d4ff] opacity-80 transition-opacity group-hover:opacity-100"
              style={{ height: `${Math.max(6, (p.intensity || 0) * 88)}px` }}
              title={p.note || ''}
            />
          </div>
          <span className="mt-1.5 text-[10px] text-[#5a5a7a]">{(p.time || 0).toFixed(0)}s</span>
        </div>
      ))}
    </div>
  )
}

/* ---------- 分析过程实时视图 ---------- */

const ANALYSIS_STAGES = [
  { key: 'video_info', label: '视频信息' },
  { key: 'scenes', label: '镜头切分' },
  { key: 'audio', label: '音频处理' },
  { key: 'shots', label: '逐镜头分析' },
  { key: 'structure', label: '全局结构分析' },
]

/* 事件类型 → 阶段序号（done 返回 5 表示全部完成） */
function stageIndexOf(type) {
  if (type === 'video_info') return 0
  if (type === 'scenes') return 1
  if (type === 'audio') return 2
  if (type === 'shot_start' || type === 'shot_result' || type === 'shot_failed') return 3
  if (type === 'structure_start' || type === 'structure_done') return 4
  if (type === 'done') return 5
  return -1
}

function formatLogTime(iso) {
  if (!iso) return ''
  const t = iso.split('T')[1] || ''
  return t.slice(0, 8)
}

function StageStepper({ currentStage, shotProgress }) {
  return (
    <div className="flex items-center">
      {ANALYSIS_STAGES.map((stage, i) => {
        const state = i < currentStage ? 'done' : i === currentStage ? 'active' : 'todo'
        return (
          <div key={stage.key} className="flex flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center gap-1.5">
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs transition-colors ${
                  state === 'done'
                    ? 'border-[#34d399] bg-[rgba(52,211,153,0.12)] text-[#6ee7b7]'
                    : state === 'active'
                      ? 'border-[#7c5cfc] bg-[rgba(124,92,252,0.15)] text-[#b49aff]'
                      : 'border-[#2a2a42] bg-[#1c1c2b] text-[#5a5a7a]'
                }`}
              >
                {state === 'done' ? (
                  <Check size={14} />
                ) : state === 'active' ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  i + 1
                )}
              </div>
              <span
                className={`whitespace-nowrap text-[10px] ${
                  state === 'active' ? 'text-[#b49aff]' : state === 'done' ? 'text-[#6ee7b7]' : 'text-[#5a5a7a]'
                }`}
              >
                {stage.label}
                {stage.key === 'shots' && state === 'active' && shotProgress
                  ? ` ${shotProgress}`
                : ''}
              </span>
            </div>
            {i < ANALYSIS_STAGES.length - 1 && (
              <div className={`mx-2 mb-5 h-px flex-1 ${i < currentStage ? 'bg-[#34d399]' : 'bg-[#2a2a42]'}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}

/* 分析过程中实时出现的镜头卡片 */
function ShotLiveCard({ ev, geneId }) {
  const d = ev.data || {}
  const failed = ev.type === 'shot_failed'
  return (
    <div className="flex gap-3 rounded-xl border border-[#2a2a42] bg-[#1c1c2b] p-3 vc-fade-in">
      {d.frame && (
        <img
          src={mediaUrl(`/genes/${geneId}/frames/${d.frame}`)}
          alt={`镜头 ${(d.index ?? 0) + 1}`}
          className="h-20 w-12 shrink-0 rounded-lg bg-black object-cover"
          onError={(e) => { e.currentTarget.style.display = 'none' }}
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-bold text-[#5a5a7a]">#{(d.index ?? 0) + 1}</span>
          <span className="text-xs text-[#5a5a7a]">{d.start}s–{d.end}s</span>
          {failed ? (
            <Badge color="red">分析失败</Badge>
          ) : (
            <>
              {d.function && <Badge color="blue">{d.function}</Badge>}
              {d.emotion && <Badge color="green">{d.emotion}</Badge>}
              {d.has_face && <Badge color="purple">人脸</Badge>}
            </>
          )}
        </div>
        {d.summary && <p className="mt-1.5 line-clamp-2 text-xs text-[#c8c8e0]">{d.summary}</p>}
        {failed && d.message && <p className="mt-1.5 line-clamp-2 text-xs text-[#fca5a5]">{d.message}</p>}
      </div>
    </div>
  )
}

/* 原始日志控制台（自动滚到底部） */
function LogConsole({ logs }) {
  const ref = useRef(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [logs.length])
  return (
    <div
      ref={ref}
      className="max-h-56 overflow-y-auto rounded-xl bg-[#0d0d15] p-3 font-mono text-[11px] leading-relaxed text-[#5a5a7a]"
    >
      {logs.length === 0 ? (
        <div>等待子进程输出...</div>
      ) : (
        logs.map((l, i) => (
          <div key={i} className={l.type === 'log' ? '' : 'text-[#66e0ff]'}>
            <span className="text-[#3d3d5c]">{formatLogTime(l.time)} </span>
            {l.message}
          </div>
        ))
      )}
    </div>
  )
}

/* 分析中主视图：步进条 + 进度条 + 镜头卡片流 + 日志 */
function AnalysisProgress({ gene }) {
  const [showLogs, setShowLogs] = useState(false)
  const logs = gene.progress_logs || []
  const events = logs.filter((l) => l.type !== 'log')
  const currentStage = events.reduce((m, e) => Math.max(m, stageIndexOf(e.type)), -1)
  const scenesEv = events.find((e) => e.type === 'scenes')
  const totalShots = scenesEv?.data?.count ?? null
  const shotEvents = events.filter((e) => e.type === 'shot_result' || e.type === 'shot_failed')
  const shotProgress = totalShots != null ? `${shotEvents.length}/${totalShots}` : null

  return (
    <>
      <Card className="mb-6 p-5">
        <SectionTitle icon={Dna}>正在提取视频基因</SectionTitle>
        <div className="mb-4">
          <StageStepper currentStage={currentStage} shotProgress={shotProgress} />
        </div>
        <div className="mb-2 flex items-center justify-between text-xs">
          <span className="text-[#8888a8]">
            {events.length ? events[events.length - 1].message : '正在启动分析子进程...'}
          </span>
          <span className="shrink-0 text-[#5a5a7a]">{gene.progress || 0}%</span>
        </div>
        <ProgressBar value={gene.progress || 0} />
        <button
          onClick={() => setShowLogs((v) => !v)}
          className="mt-4 flex items-center gap-1.5 text-xs text-[#8888a8] transition-colors hover:text-[#c8c8e0]"
        >
          <Terminal size={13} />
          详细日志
          {showLogs ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
        {showLogs && (
          <div className="mt-3">
            <LogConsole logs={logs} />
          </div>
        )}
      </Card>

      {shotEvents.length > 0 && (
        <Card className="mb-6 p-5">
          <SectionTitle icon={Clapperboard}>
            逐镜头分析结果（{shotEvents.length}{totalShots != null ? ` / ${totalShots}` : ''}）
          </SectionTitle>
          <div className="space-y-2.5">
            {shotEvents.map((ev, i) => (
              <ShotLiveCard key={i} ev={ev} geneId={gene.id} />
            ))}
          </div>
        </Card>
      )}
    </>
  )
}

export default function GeneDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [gene, setGene] = useState(null)
  const [extracting, setExtracting] = useState(false)
  const [extractMsg, setExtractMsg] = useState(null)
  const [activeTab, setActiveTab] = useState('overview')
  const geneStatus = gene?.status

  useEffect(() => {
    getGene(id).then((res) => setGene(res.data)).catch(() => navigate('/genes'))
  }, [id, navigate])

  // 分析中轮询
  useEffect(() => {
    if (!geneStatus || geneStatus === 'done' || geneStatus === 'failed') return
    const timer = setInterval(() => {
      getGene(id).then((res) => setGene(res.data)).catch(() => {})
    }, 3000)
    return () => clearInterval(timer)
  }, [geneStatus, id])

  const handleExtract = async () => {
    setExtracting(true)
    setExtractMsg(null)
    try {
      const res = await extractGeneKnowledge(id)
      setExtractMsg({
        type: 'success',
        text: res.data.skipped
          ? `该基因已有 ${res.data.existing} 条知识，${res.data.demos_available || 0} 个视频示例可用`
          : `已提炼 ${res.data.added} 条知识，生成 ${res.data.demos_available || 0} 个视频示例`,
      })
    } catch (err) {
      setExtractMsg({ type: 'error', text: err.response?.data?.detail || '提炼失败' })
    } finally {
      setExtracting(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('确定删除该基因？')) return
    await deleteGene(id)
    navigate('/genes')
  }

  if (!gene) {
    return <div className="py-16 text-center text-sm text-[#5a5a7a]">加载中...</div>
  }

  const report = gene.report
  const sa = report?.raw_structure_analysis || {}
  const meta = report?.vlog_meta || {}
  const hook = sa.hook_strategy || {}
  const rhythm = sa.rhythm_analysis || {}
  const packaging = sa.packaging_analysis || {}
  const st = sa.structure_type || {}

  return (
    <div>
      <SectionHeader
        title={geneDisplayTitle(gene)}
        description={gene.source_filename}
        backTo="/genes"
        actions={
          <>
            {gene.status === 'done' && (
              <>
                <Button variant="secondary" icon={BookOpen} loading={extracting} onClick={handleExtract}>
                  提炼知识入库
                </Button>
                <Button icon={Sparkles} onClick={() => navigate(`/projects?gene=${gene.id}`)}>
                  用此基因创建项目
                </Button>
              </>
            )}
            <Button variant="danger" icon={Trash2} onClick={handleDelete}>
              删除
            </Button>
          </>
        }
      />

      {extractMsg && (
        <div className="mb-6 vc-fade-in">
          <InfoBar type={extractMsg.type}>
            {extractMsg.text}
            {extractMsg.type === 'success' && (
              <button
                className="ml-2 underline"
                onClick={() => navigate('/knowledge')}
              >
                去知识库看看 →
              </button>
            )}
          </InfoBar>
        </div>
      )}

      {/* 分析中 / 失败状态 */}
      {gene.status !== 'done' && (
        <>
          {gene.status === 'failed' ? (
            <Card className="mb-6 p-5">
              <InfoBar type="error">{gene.error_message || '提取失败'}</InfoBar>
              {(gene.progress_logs || []).length > 0 && (
                <div className="mt-4">
                  <SectionTitle icon={Terminal}>失败前的分析日志</SectionTitle>
                  <LogConsole logs={gene.progress_logs} />
                </div>
              )}
            </Card>
          ) : (
            <AnalysisProgress gene={gene} />
          )}
        </>
      )}

      {/* 视频预览 */}
      <Card className="vc-gene-source mb-6 p-5">
        <SectionTitle icon={Clapperboard}>源视频</SectionTitle>
        <div className="vc-gene-source-layout">
          <div className="vc-gene-source-player"><video src={mediaUrl(`/genes/${gene.id}/video`)} controls playsInline preload="metadata" /></div>
          <div className="vc-gene-source-facts">
            <span className="vc-gene-source-kicker">GENE {String(gene.id).padStart(2, '0')}</span>
            <h3>{compactText(gene.structure_type || st.category || '视频结构分析', 24)}</h3>
            <div className="vc-gene-metrics"><span><strong>{Number(gene.duration || report?.duration || 0).toFixed(1)}</strong>秒</span><span><strong>{gene.shot_count || report?.shot_count || 0}</strong>镜头</span></div>
            <dl><div><dt>开场方式</dt><dd>{compactText(gene.hook_method || hook.method || '—', 28)}</dd></div><div><dt>整体情绪</dt><dd>{compactText(gene.overall_emotion || sa.overall_emotion || '—', 28)}</dd></div></dl>
            <p className="vc-gene-original-title">原始名称：{gene.title}</p>
          </div>
        </div>
      </Card>

      {report && (
        <>
          <div className="vc-report-tabs" aria-label="分析维度">{[['overview', '核心概览'], ['hook', '开场 Hook'], ['structure', '结构与节奏'], ['packaging', '包装风格'], ['shots', `镜头标注 · ${report.shots?.length || 0}`]].map(([key, label]) => <button type="button" key={key} aria-pressed={activeTab === key} onClick={() => setActiveTab(key)} className={activeTab === key ? 'is-active' : ''}>{label}</button>)}</div>
          {/* 基因概览 */}
          {activeTab === 'overview' && (
          <Card className="mb-6 p-5">
            <SectionTitle icon={Dna}>基因概览</SectionTitle>
            <div className="mb-4 flex flex-wrap gap-1.5">
              {st.category && <Badge color="indigo">{compactText(st.category, 16)}</Badge>}
              {meta.narrative_type && <Badge color="blue">叙事: {compactText(meta.narrative_type, 16)}</Badge>}
              {sa.persona_type && <Badge color="purple">人设: {compactText(sa.persona_type, 16)}</Badge>}
              {sa.overall_emotion && <Badge color="green">情绪: {compactText(sa.overall_emotion, 16)}</Badge>}
              <Badge color="gray">{report.duration?.toFixed(1)}s</Badge>
              <Badge color="gray">{report.shot_count} 镜头</Badge>
              {report.resolution && <Badge color="gray">{report.resolution.join('×')}</Badge>}
            </div>
            {sa.overall_summary && (
              <ReportText text={sa.overall_summary} />
            )}
            {st.core_characteristics && (
              <div className="mt-3"><ReportRow label="结构特征">{st.core_characteristics}</ReportRow></div>
            )}
          </Card>
          )}

          {/* Hook 策略 */}
          {activeTab === 'hook' && <Card className="mb-6 p-5">
            <SectionTitle icon={Zap}>前 3 秒 Hook 策略</SectionTitle>
            <div className="divide-y divide-[#2a2a42]">
              <ReportRow label="方法">{hook.method}</ReportRow>
              <ReportRow label="具体手法">{hook.detail || report.hook_summary}</ReportRow>
              <ReportRow label="效果评估">{hook.effectiveness}</ReportRow>
              <ReportRow label="与正文衔接">{hook.connection_to_body}</ReportRow>
            </div>
          </Card>}

          {/* 段落结构 */}
          {activeTab === 'structure' && sa.script_structure?.length > 0 && (
            <Card className="mb-6 p-5">
              <SectionTitle icon={Scissors}>脚本段落结构</SectionTitle>
              <div className="space-y-3">
                {sa.script_structure.map((seg) => (
                  <div
                    key={seg.index}
                    className="rounded-xl border border-[#2a2a42] bg-[#1c1c2b] p-4"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-bold text-[#5a5a7a]">#{seg.index}</span>
                      <Badge color={PURPOSE_COLORS[seg.purpose] || 'indigo'}>{seg.purpose}</Badge>
                      <span className="text-xs text-[#8888a8]">{seg.shot_range}</span>
                      <span className="ml-auto text-xs text-[#5a5a7a]">
                        {seg.emotion} · 节奏{seg.rhythm}
                      </span>
                    </div>
                    <div className="mt-2"><ReportText text={seg.content_summary} /></div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* 节奏分析 */}
          {activeTab === 'structure' && rhythm.curve_points?.length > 0 && (
            <Card className="mb-6 p-5">
              <SectionTitle icon={Music}>节奏曲线</SectionTitle>
              <RhythmChart points={rhythm.curve_points} />
              <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-[#8888a8]">
                {rhythm.pattern && <span>模式: {rhythm.pattern}</span>}
                {rhythm.estimated_bpm_range && <span>BPM: {rhythm.estimated_bpm_range}</span>}
                {rhythm.climax_position_percent != null && (
                  <span>高潮位置: {rhythm.climax_position_percent}%</span>
                )}
                {rhythm.front_3s_shot_count != null && (
                  <span>前 3 秒: {rhythm.front_3s_shot_count} 个镜头</span>
                )}
              </div>
              {rhythm.bgm_style_guess && <div className="mt-3"><ReportRow label="BGM 风格">{rhythm.bgm_style_guess}</ReportRow></div>}
            </Card>
          )}

          {/* 包装分析 + 关键技法 */}
          {activeTab === 'packaging' && <div className="mb-6">
            <Card className="p-5">
              <SectionTitle icon={Scissors}>包装风格</SectionTitle>
              <div className="divide-y divide-[#2a2a42]">
                <ReportRow label="字幕样式">
                  {packaging.subtitle_font_guess}
                  {packaging.subtitle_color_and_stroke
                    ? ` · ${packaging.subtitle_color_and_stroke}`
                    : ''}
                </ReportRow>
                <ReportRow label="字幕动效">{packaging.subtitle_animation}</ReportRow>
                <ReportRow label="调色风格">
                  {packaging.color_grade}
                  {packaging.color_grade_detail ? ` · ${packaging.color_grade_detail}` : ''}
                </ReportRow>
                <ReportRow label="转场习惯">
                  {packaging.transitions_used?.length
                    ? packaging.transitions_used.map((t) => t.type).filter(Boolean).join('、')
                    : '—'}
                </ReportRow>
              </div>
            </Card>
          </div>}

            {activeTab === 'overview' && <Card className="mb-6 p-5">
              <SectionTitle icon={Sparkles}>关键技法</SectionTitle>
              <div className="vc-technique-list">
                {(report.key_techniques || []).map((t, i) => (
                  <details key={i}><summary><span>{String(i + 1).padStart(2, '0')}</span><strong>{shortHeading(t, 36)}</strong><ChevronDown size={14} /></summary><p>{t}</p></details>
                ))}
                {(!report.key_techniques || report.key_techniques.length === 0) && (
                  <span className="text-sm text-[#5a5a7a]">—</span>
                )}
              </div>
            </Card>}

          {/* 逐镜头标注 */}
          {activeTab === 'shots' && report.shots?.length > 0 && (
            <Card className="p-5">
              <SectionTitle icon={Clapperboard}>逐镜头功能标注（{report.shots.length} 个镜头）</SectionTitle>
              <ul className="divide-y divide-[#2a2a42]">
                {report.shots.map((s, i) => (
                  <li key={i} className="flex items-start gap-3 py-2.5">
                    <img
                      src={mediaUrl(`/genes/${gene.id}/frames/shot_${String(s.index ?? i).padStart(3, '0')}.jpg`)}
                      alt={`镜头 ${(s.index ?? i) + 1}`}
                      className="mt-0.5 h-16 w-10 shrink-0 rounded-md bg-black object-cover"
                      loading="lazy"
                      onError={(e) => { e.currentTarget.style.display = 'none' }}
                    />
                    <span className="mt-0.5 w-8 shrink-0 text-xs font-bold text-[#5a5a7a]">
                      {(s.index ?? i) + 1}
                    </span>
                    <div className="flex flex-1 flex-wrap items-center gap-2">
                      <Badge color="blue">{s.shot_type || 'unknown'}</Badge>
                      {s.emotion && <Badge color="green">{s.emotion}</Badge>}
                      {s.has_face && <Badge color="purple">人脸</Badge>}
                      <div className="w-full min-w-0"><ReportText text={s.visual_description} /></div>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
