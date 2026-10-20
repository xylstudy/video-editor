import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Dna, FileVideo, Loader2, Plus, Search, Sparkles, Trash2 } from 'lucide-react'
import { createGene, deleteGene, listGenes, mediaUrl } from '../api.js'
import { compactText, geneDisplayTitle } from '../library.js'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  InfoBar,
  ProgressBar,
  SectionHeader,
  TextInput,
} from '../components/ui.jsx'

const GENE_STATUS = {
  pending: '排队中',
  analyzing: '分析中',
  done: '已完成',
  failed: '失败',
}

/* 从进度日志推导当前阶段的可读描述（用于分析中的卡片） */
const STAGE_LABELS = {
  video_info: '读取视频信息',
  scenes: '镜头切分',
  audio: '音频处理',
  shot_start: '逐镜头分析',
  shot_result: '逐镜头分析',
  shot_failed: '逐镜头分析',
  structure_start: '全局结构分析',
  structure_done: '全局结构分析',
  done: '收尾',
}

function latestStageLabel(g) {
  const events = (g.progress_logs || []).filter((l) => l.type !== 'log')
  if (!events.length) return '正在启动分析...'
  const last = events[events.length - 1]
  if (last.type === 'shot_start' || last.type === 'shot_result' || last.type === 'shot_failed') {
    const d = last.data || {}
    const done = last.type === 'shot_start' ? (d.index ?? 0) : (d.index ?? 0) + 1
    return `逐镜头分析 ${done}/${d.total ?? '?'}`
  }
  return STAGE_LABELS[last.type] || '分析中'
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function GeneCover({ gene }) {
  const [failed, setFailed] = useState(false)
  return (
    <div className="vc-gene-cover">
      {gene.status === 'done' && !failed ? <img src={mediaUrl(`/genes/${gene.id}/frames/shot_000.jpg`)} alt={`${geneDisplayTitle(gene)}关键帧`} loading="lazy" onError={() => setFailed(true)} /> : <span className="vc-gene-cover-placeholder"><FileVideo size={30} strokeWidth={1.3} /><small>参考视频</small></span>}
      <span className="vc-gene-cover-status"><Badge color={gene.status === 'done' ? 'green' : gene.status === 'failed' ? 'red' : 'indigo'}>{(gene.status === 'pending' || gene.status === 'analyzing') && <Loader2 size={11} className="animate-spin" />}{GENE_STATUS[gene.status] || gene.status}</Badge></span>
      <span className="vc-gene-cover-id">GENE {String(gene.id).padStart(2, '0')}</span>
    </div>
  )
}

export default function Genes() {
  const [genes, setGenes] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [title, setTitle] = useState('')
  const [file, setFile] = useState(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const fileRef = useRef(null)

  const fetchGenes = async () => {
    try {
      const res = await listGenes()
      setGenes(res.data)
      return res.data
    } catch (err) {
      setError(err.response?.data?.detail || '基因库加载失败')
    } finally {
      setLoading(false)
    }
  }

  // 有基因处于分析中 → 每 3 秒轮询
  useEffect(() => {
    fetchGenes()
  }, [])

  useEffect(() => {
    const hasActive = genes.some((g) => g.status === 'pending' || g.status === 'analyzing')
    if (!hasActive) return
    const timer = setInterval(fetchGenes, 3000)
    return () => clearInterval(timer)
  }, [genes])

  const submit = async (useSample) => {
    setError('')
    if (!useSample && !file) {
      setError('请选择视频文件，或改用示例视频')
      return
    }
    if (!title.trim()) {
      setError('请填写视频名称')
      return
    }
    setCreating(true)
    try {
      await createGene(title.trim(), useSample ? null : file, useSample)
      setTitle('')
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      setShowCreate(false)
      fetchGenes()
    } catch (err) {
      setError(err.response?.data?.detail || '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (e, id) => {
    e.preventDefault()
    e.stopPropagation()
    if (!confirm('确定删除该基因？')) return
    try {
      await deleteGene(id)
      fetchGenes()
    } catch (err) {
      setError(err.response?.data?.detail || '删除基因失败')
    }
  }

  if (loading) {
    return <div className="py-16 text-center text-sm text-[#5a5a7a]">加载中...</div>
  }

  const keyword = query.trim().toLowerCase()
  const filteredGenes = genes.filter((gene) => (
    (!status || (status === 'active' ? ['pending', 'analyzing'].includes(gene.status) : gene.status === status))
    && (!keyword || [gene.title, gene.source_filename, gene.structure_type, gene.hook_method, gene.overall_emotion].some((value) => String(value || '').toLowerCase().includes(keyword)))
  ))

  return (
    <div>
      <SectionHeader
        title="视频基因库"
        description="通过关键帧与结构标签挑选参考，再查看分析或创建项目"
        actions={
          <Button icon={Plus} onClick={() => setShowCreate((v) => !v)}>
            提取新基因
          </Button>
        }
      />

      {!showCreate && error && <div className="mb-4"><InfoBar type="error">{error}</InfoBar></div>}

      {showCreate && (
        <Card className="mb-6 p-5 vc-fade-in">
          <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
            <Dna size={16} className="text-[#66e0ff]" />
            提取视频基因
          </h2>
          <div className="flex flex-wrap items-end gap-4">
            <Field label="视频名称" className="min-w-[200px] flex-1">
              <TextInput
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="例如：北京旅行爆款 Vlog"
              />
            </Field>
            <Field label="视频文件" className="min-w-[220px]">
              <input
                ref={fileRef}
                type="file"
                accept="video/*"
                onChange={(e) => setFile(e.target.files[0] || null)}
                className="w-full rounded-lg border border-[#2a2a42] bg-[#1c1c2b] px-3 py-1.5 text-sm text-[#8888a8] file:mr-3 file:rounded-md file:border-0 file:bg-[#2a2a42] file:px-3 file:py-1.5 file:text-xs file:text-[#c8c8e0] hover:file:bg-[#35355a]"
              />
            </Field>
            <div className="flex gap-2">
              <Button loading={creating} onClick={() => submit(false)}>
                开始提取
              </Button>
              <Button
                variant="secondary"
                icon={Sparkles}
                loading={creating}
                onClick={() => submit(true)}
              >
                用示例视频
              </Button>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                取消
              </Button>
            </div>
          </div>
          <p className="mt-3 text-xs text-[#5a5a7a]">
            提取过程需要调用多模态大模型逐镜头分析，通常需要几分钟，期间可离开本页
          </p>
          {error && (
            <div className="mt-4">
              <InfoBar type="error">{error}</InfoBar>
            </div>
          )}
        </Card>
      )}

      <div className="vc-library-toolbar">
        <div className="vc-library-filters" aria-label="基因状态筛选">{[['', '全部'], ['done', '已就绪'], ['active', '分析中'], ['failed', '失败']].map(([value, label]) => <button type="button" key={value} aria-pressed={status === value} className={status === value ? 'is-active' : ''} onClick={() => setStatus(value)}>{label}</button>)}</div>
        <div className="vc-library-search"><Search size={15} /><TextInput value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称 / 结构 / 情绪" aria-label="搜索基因" /></div>
      </div>

      {genes.length === 0 ? (
        <Card>
          <EmptyState
            icon={Dna}
            title="还没有视频基因"
            description="上传一条爆款视频，或直接用示例视频体验基因提取"
          >
            <Button icon={Plus} onClick={() => setShowCreate(true)}>
              提取第一个基因
            </Button>
          </EmptyState>
        </Card>
      ) : filteredGenes.length === 0 ? (
        <Card><EmptyState icon={Search} title="没有匹配的视频基因" description="换一个名称、结构或状态试试" /></Card>
      ) : (
        <>
          <p className="vc-library-count">{filteredGenes.length} 个参考 · {genes.filter((gene) => gene.status === 'done').length} 个已就绪</p>
          <div className="vc-gene-grid">
            {filteredGenes.map((g) => (
              <Card key={g.id} hover className="vc-gene-card">
                <Link to={`/genes/${g.id}`} aria-label={`查看基因分析：${g.title}`}><GeneCover gene={g} /></Link>
                <div className="vc-gene-card-body">
                  <div className="vc-gene-card-heading"><Link to={`/genes/${g.id}`} title={g.title}><h3>{geneDisplayTitle(g)}</h3></Link><button type="button" onClick={(event) => handleDelete(event, g.id)} className="vc-library-delete" aria-label={`删除基因：${g.title}`} title="删除基因"><Trash2 size={14} /></button></div>
                  {g.status === 'done' ? <>
                    <div className="vc-gene-metrics"><span><strong>{Number(g.duration || 0).toFixed(1)}</strong>秒</span><span><strong>{g.shot_count || 0}</strong>镜头</span><span title="平均镜头时长"><strong>{g.shot_count > 0 ? (Number(g.duration || 0) / g.shot_count).toFixed(1) : '—'}</strong>秒 / 镜</span></div>
                    <div className="vc-gene-identity"><Badge color="indigo">{compactText(g.structure_type || '结构已提取', 14)}</Badge><span title={g.hook_method}>{compactText(g.hook_method || '—', 16)}</span><span title={g.overall_emotion}>{compactText(g.overall_emotion || '—', 12)}</span></div>
                  </> : g.status === 'failed' ? <p className="vc-gene-error">{compactText(g.error_message || '提取失败，点开查看详情', 72)}</p> : <div className="vc-gene-progress"><span>{latestStageLabel(g)}</span><small>{g.progress || 0}%</small><ProgressBar value={g.progress || 0} /></div>}
                  <div className="vc-gene-card-footer"><span>{formatDate(g.created_at)}</span><Link to={`/genes/${g.id}`}>查看分析 <ArrowUpRight size={13} /></Link>{g.status === 'done' && <Link className="vc-gene-use" to={`/projects?gene=${g.id}`}>用此基因</Link>}</div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
