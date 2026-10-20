import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, ArrowUpRight, Download, Film, Play, PlaySquare, RefreshCw, Search } from 'lucide-react'
import { listWorks, mediaUrl } from '../api.js'
import { Badge, Button, Card, EmptyState, InfoBar, SectionHeader, TextInput } from '../components/ui.jsx'
import LibraryDetail from '../components/LibraryDetail.jsx'
import MediaCover from '../components/MediaCover.jsx'
import { compactText } from '../library.js'

const MODE_LABEL = { editing_transfer: '编辑迁移', agent_pipeline: '多智能体' }

function formatDate(value, full = false) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return full ? date.toLocaleString('zh-CN') : date.toLocaleDateString('zh-CN')
}

export default function Works() {
  const [works, setWorks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState('')
  const [selected, setSelected] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try { setWorks((await listWorks()).data) }
    catch (err) { setError(err.response?.data?.detail || '作品加载失败，请稍后重试') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const keyword = query.trim().toLowerCase()
  const filtered = works.filter((work) => (!mode || work.pipeline_mode === mode) && (!keyword || [work.project_name, work.reference_filename, String(work.task_id)].some((value) => String(value || '').toLowerCase().includes(keyword))))

  return (
    <div>
      <SectionHeader title="作品集" description="浏览生成成片，点开对照参考视频与完整结果" actions={<Button variant="secondary" icon={RefreshCw} loading={loading} onClick={load}>刷新作品</Button>} />
      <div className="vc-library-toolbar">
        <div className="vc-library-filters" aria-label="作品模式筛选">{[['', '全部作品'], ['agent_pipeline', '多智能体'], ['editing_transfer', '编辑迁移']].map(([value, label]) => <button type="button" key={value} aria-pressed={mode === value} className={mode === value ? 'is-active' : ''} onClick={() => setMode(value)}>{label}</button>)}</div>
        <div className="vc-library-search"><Search size={15} /><TextInput value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目 / 任务 / 参考视频" aria-label="搜索作品" /></div>
      </div>
      {error && <div className="mb-4"><InfoBar type="error">{error}</InfoBar></div>}
      {loading && !works.length ? <div className="py-16 text-center text-sm text-[#8b8495]">正在加载作品…</div> : error && !works.length ? null : !filtered.length ? (
        <Card><EmptyState icon={works.length ? Search : PlaySquare} title={works.length ? '没有匹配的作品' : '还没有成片'} description={works.length ? '换一个项目名、任务编号或生成模式试试' : '完成一次端到端生成后，成片会出现在这里'}>{!works.length && <Link className="vc-library-source-link" to="/projects">去创建项目 <ArrowUpRight size={14} /></Link>}</EmptyState></Card>
      ) : <>
        <p className="vc-library-count">{filtered.length} 个作品 · {new Set(filtered.map((work) => work.project_id)).size} 个项目</p>
        <div className="vc-work-gallery">
          {filtered.map((work) => (
            <Card hover key={work.task_id} className="vc-work-gallery-card">
              <button type="button" className="vc-work-open" onClick={() => setSelected(work)} aria-label={`对照播放作品：任务 ${work.task_id}`}>
                <MediaCover videoSrc={mediaUrl(`/tasks/${work.task_id}/download`)} alt={`${work.project_name || '生成作品'}成片封面`}>
                  <span className="vc-work-cover-badge"><Badge color="green">已生成</Badge></span>
                  <span className="vc-work-cover-play"><Play size={18} fill="currentColor" /></span>
                  <span className="vc-work-cover-id">WORK {String(work.task_id).padStart(2, '0')}</span>
                </MediaCover>
                <span className="vc-work-card-body">
                  <span className="vc-work-card-tags"><Badge color="indigo">{MODE_LABEL[work.pipeline_mode] || work.pipeline_mode}</Badge><small>{Number(work.size_mb || 0).toFixed(1)} MB</small></span>
                  <strong className="vc-work-gallery-title" title={work.project_name}>{compactText(work.project_name || `生成作品 #${work.task_id}`, 44)}</strong>
                  <span className="vc-work-reference-note"><Film size={12} />{work.reference_material_id ? '已关联参考视频，可并排对照' : '历史作品未关联参考视频'}</span>
                </span>
              </button>
              <div className="vc-work-gallery-footer"><span>{formatDate(work.created_at)} · #{work.task_id}</span><div><a href={mediaUrl(`/tasks/${work.task_id}/download`)} download className="vc-work-download" aria-label={`下载作品 ${work.task_id}`} title="下载成片"><Download size={14} /></a><button type="button" onClick={() => setSelected(work)} className="vc-library-detail-button">对照播放 <ArrowUpRight size={13} /></button></div></div>
            </Card>
          ))}
        </div>
      </>}

      {selected && <LibraryDetail key={selected.task_id} className="vc-work-detail-dialog" title={selected.project_name || `生成作品 #${selected.task_id}`} subtitle={`作品对照 · 任务 #${selected.task_id}`} closeLabel="关闭作品对照" onClose={() => setSelected(null)}>
        <div className="vc-work-detail-meta"><Badge color="indigo">{MODE_LABEL[selected.pipeline_mode] || selected.pipeline_mode}</Badge><span>{selected.size_mb} MB</span><span>{formatDate(selected.created_at, true)}</span></div>
        <div className="vc-work-compare">
          <section className="min-w-0"><div className="vc-work-video-head"><span><Film size={14} />参考视频</span></div>{selected.reference_material_id ? <video className="vc-work-video" src={mediaUrl(`/materials/${selected.reference_material_id}/media`)} controls preload="metadata" playsInline aria-label="参考视频" /> : <div className="vc-work-video vc-work-missing">该历史作品没有可用的参考视频记录</div>}<p className="vc-work-media-caption">{selected.reference_filename || '未记录参考文件'}</p></section>
          <div className="vc-work-divider" aria-hidden="true"><ArrowRight size={19} /></div>
          <section className="min-w-0"><div className="vc-work-video-head"><span><PlaySquare size={14} />生成成片</span><Badge color="green">任务 #{selected.task_id}</Badge></div><video className="vc-work-video" src={mediaUrl(`/tasks/${selected.task_id}/download`)} controls preload="metadata" playsInline aria-label="生成成片" /><p className="vc-work-media-caption">当前任务的最终渲染结果</p></section>
        </div>
        <div className="vc-work-detail-actions"><Link to={`/tasks/${selected.task_id}`} className="vc-library-source-link">查看任务与评审 <ArrowUpRight size={14} /></Link><Link to={`/projects/${selected.project_id}`} className="vc-library-source-link">打开项目 <ArrowUpRight size={14} /></Link><a href={mediaUrl(`/tasks/${selected.task_id}/download`)} download className="vc-action-link"><Download size={14} />下载成片</a></div>
      </LibraryDetail>}
    </div>
  )
}
