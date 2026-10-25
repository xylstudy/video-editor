import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, BookOpen, Library, PlayCircle, Search, Trash2, UserRound } from 'lucide-react'
import { deleteKnowledge, listKnowledge, mediaUrl } from '../api.js'
import { Badge, Card, EmptyState, InfoBar, SectionHeader, TextInput } from '../components/ui.jsx'
import LibraryDetail from '../components/LibraryDetail.jsx'
import KnowledgeVisual from '../components/KnowledgeVisual.jsx'
import { compactText, firstSentence, shortHeading } from '../library.js'

const TYPE_TABS = [
  { key: '', label: '全部' },
  { key: 'transition_type', label: '转场' },
  { key: 'editing_technique', label: '剪辑技法' },
  { key: 'packaging_style', label: '包装风格' },
  { key: 'effect_type', label: '特效 / 贴纸' },
  { key: 'structure_template', label: '结构模板' },
  { key: 'hook_technique', label: 'Hook 技法' },
  { key: 'rhythm_pattern', label: '节奏模式' },
  { key: 'emotion_design', label: '情绪设计' },
]

const TYPE_BADGE = {
  transition_type: 'blue',
  editing_technique: 'indigo',
  packaging_style: 'purple',
  effect_type: 'amber',
  structure_template: 'green',
  hook_technique: 'red',
  rhythm_pattern: 'blue',
  emotion_design: 'green',
}

const TYPE_LABEL = Object.fromEntries(TYPE_TABS.filter((t) => t.key).map((t) => [t.key, t.label]))

const SOURCE_TABS = [
  { key: 'mine', label: '我的知识', icon: UserRound },
  { key: 'system', label: '系统技法', icon: Library },
]

/** 技法演示播放器：默认收起，点击后加载视频（避免整页同时加载几十个视频） */
function DemoPlayer({ id, demos, initiallyOpen = false }) {
  const [open, setOpen] = useState(initiallyOpen)
  const [failed, setFailed] = useState(false)
  const [variant, setVariant] = useState(demos[0].variant)
  const currentDemo = demos.find((demo) => demo.variant === variant) || demos[0]

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-3 flex items-center justify-center gap-1.5 rounded-lg border border-[#2a2a42] bg-[rgba(124,92,252,0.08)] px-3 py-2 text-xs font-medium text-[#b49aff] transition-colors hover:bg-[rgba(124,92,252,0.16)]"
      >
        <PlayCircle size={14} />
        播放演示
      </button>
    )
  }

  return (
    <div className="mt-3">
      {demos.length > 1 && <div className="vc-demo-variants" role="group" aria-label="选择演示类型">{demos.map((demo) => <button key={demo.variant} type="button" aria-pressed={variant === demo.variant} onClick={() => { setVariant(demo.variant); setFailed(false) }}>{demo.label}</button>)}</div>}
      <p className="vc-demo-caption">{currentDemo.description || (currentDemo.variant === 'teaching' ? '播放这条知识对应的实拍剪辑效果。打开声音可听示例鼓点。' : currentDemo.label === '原片示例' ? '截取自来源参考视频，观察知识在实际画面中的应用。' : '观察技法在画面中的变化。')}</p>
      {failed ? <InfoBar type="error">演示视频暂时无法播放。<button type="button" className="ml-2 underline" onClick={() => setFailed(false)}>重新加载</button></InfoBar> :
      <div className="overflow-hidden rounded-lg bg-black">
      <video
        key={`${variant}:${currentDemo.version || ''}`}
        src={mediaUrl(`/knowledge/${encodeURIComponent(id)}/demo${variant === 'teaching' ? `?variant=teaching${currentDemo.version ? `&v=${encodeURIComponent(currentDemo.version)}` : ''}` : ''}`)}
        controls
        autoPlay
        loop
        playsInline
        aria-label={`${currentDemo.label}视频`}
        onError={() => setFailed(true)}
        className={`vc-technique-demo-video${variant === 'teaching' ? ' vc-real-edit-demo' : ''}`}
      />
      </div>}
    </div>
  )
}

export default function Knowledge() {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [scope, setScope] = useState('mine')
  const [type, setType] = useState('')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState(null)
  const [demoRequested, setDemoRequested] = useState(false)
  const [error, setError] = useState('')
  const latestRequest = useRef(0)
  const openEntry = (entry, playDemo = false) => {
    setDemoRequested(playDemo)
    setSelected(entry)
  }

  const fetchEntries = useCallback(async () => {
    const request = ++latestRequest.current
    setLoading(true)
    setError('')
    try {
      const res = await listKnowledge({ scope, ...(type ? { type } : {}), ...(q.trim() ? { q: q.trim() } : {}) })
      if (request === latestRequest.current) setEntries(res.data)
    } catch (err) {
      if (request === latestRequest.current) setError(err.response?.data?.detail || '知识库加载失败，请稍后重试')
    } finally {
      if (request === latestRequest.current) setLoading(false)
    }
  }, [q, scope, type])

  // 类型切换立即刷新；搜索输入做 350ms 防抖。
  useEffect(() => {
    const timer = setTimeout(fetchEntries, q ? 350 : 0)
    return () => { clearTimeout(timer); latestRequest.current += 1 }
  }, [fetchEntries, q])

  const handleDelete = async (id) => {
    if (!confirm('确定删除该知识条目？')) return
    try {
      await deleteKnowledge(id)
      if (selected?.id === id) setSelected(null)
      fetchEntries()
    } catch (err) {
      setError(err.response?.data?.detail || '删除知识失败')
    }
  }

  const handleScopeChange = (nextScope) => {
    setScope(nextScope)
    setType('')
    setQ('')
    setSelected(null)
  }

  const hasFilters = Boolean(type || q)
  const emptyTitle = hasFilters
    ? '没有匹配的知识条目'
    : scope === 'mine'
      ? '还没有个人知识'
      : '暂无系统技法'
  const emptyDescription = hasFilters
    ? '换个类型或关键词试试'
    : scope === 'mine'
      ? '去基因库提炼知识后，它们会出现在这里'
      : '系统暂未配置内置剪辑技法'

  return (
    <div>
      <SectionHeader
        title="知识库"
        description="快速浏览技法，点开查看完整用法与视频示例"
      />

      <div className="mb-4 inline-flex rounded-xl border border-[#2a2a42] bg-[#141421] p-1">
        {SOURCE_TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => handleScopeChange(key)}
            aria-pressed={scope === key}
            className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              scope === key
                ? 'bg-[#7c5cfc] text-white'
                : 'text-[#8888a8] hover:bg-[#1c1c2b] hover:text-[#c8c8e0]'
            }`}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>

      {/* 类型 Tab + 搜索 */}
      <div className="vc-library-toolbar">
        <div className="vc-knowledge-filters">
          {TYPE_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setType(t.key)}
              aria-pressed={type === t.key}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                type === t.key
                  ? 'bg-[#7c5cfc] text-white'
                  : 'bg-[#1c1c2b] text-[#8888a8] hover:bg-[#24243a] hover:text-[#c8c8e0]'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#5a5a7a]" />
          <TextInput
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索标题 / 内容 / 标签"
            aria-label="搜索知识"
            className="pl-8"
            style={{ paddingLeft: '2rem' }}
          />
        </div>
      </div>

      {error && <div className="mb-4"><InfoBar type="error">{error}</InfoBar></div>}
      {loading ? (
        <div className="py-16 text-center text-sm text-[#5a5a7a]">加载中...</div>
      ) : entries.length === 0 ? (
        <Card>
          <EmptyState
            icon={BookOpen}
            title={emptyTitle}
            description={emptyDescription}
          />
        </Card>
      ) : (
        <>
          <p className="mb-3 text-xs text-[#5a5a7a]">共 {entries.length} 条 · {scope === 'mine' ? `${entries.filter((entry) => entry.has_teaching_demo).length} 个剪辑示例 · ${entries.filter((entry) => entry.demos?.some((demo) => demo.variant === 'example')).length} 个原片示例` : `${entries.filter((entry) => entry.has_demo).length} 个视频演示`}</p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {entries.map((e) => (
              <Card key={e.id} hover className="vc-knowledge-card" data-knowledge-id={e.id}>
                <button type="button" className="vc-knowledge-card-open" onClick={() => openEntry(e)} aria-label={`查看知识：${e.title}`}>
                  <KnowledgeVisual entry={e} />
                  <span className="vc-knowledge-card-content">
                  <span className="vc-knowledge-card-badges">
                  <Badge color={TYPE_BADGE[e.type] || 'gray'}>
                    {TYPE_LABEL[e.type] || e.type}
                  </Badge>
                  {e.has_demo && <span className="vc-demo-indicator"><PlayCircle size={12} />{e.has_teaching_demo ? '有剪辑示例' : e.source === 'system' ? '有技法演示' : '有视频示例'}</span>}
                  </span>
                  <strong className="vc-knowledge-card-title" title={e.title}>{shortHeading(e.title, 30)}</strong>
                  <span className="vc-knowledge-card-summary">{firstSentence(e.content)}</span>
                  <span className="vc-knowledge-card-use" title={e.best_when || ''}>{e.best_when ? `适用 · ${compactText(e.best_when, 36)}` : '点开查看技法说明'}</span>
                  </span>
                </button>
                <div className="vc-knowledge-card-footer">
                  <span>{e.derivation?.source_gene_id ? `来自基因 #${e.derivation.source_gene_id}` : e.source === 'user' ? '个人经验' : '系统技法'}</span>
                  <div>
                    {e.mine && <button type="button" onClick={() => handleDelete(e.id)} className="vc-library-delete" aria-label={`删除知识：${e.title}`} title="删除知识"><Trash2 size={14} /></button>}
                    {e.has_demo && <button type="button" onClick={() => openEntry(e, true)} className="vc-library-demo-button" aria-label={`播放技法演示：${e.title}`}><PlayCircle size={13} />播放演示</button>}
                    <button type="button" onClick={() => openEntry(e)} className="vc-library-detail-button">查看用法 <ArrowUpRight size={13} /></button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
      {selected && (
        <LibraryDetail key={selected.id} title={selected.title} subtitle={TYPE_LABEL[selected.type] || '技法详情'} onClose={() => setSelected(null)}>
          <KnowledgeVisual entry={selected} />
          {selected.demo_pending_reason && <InfoBar type="info">效果示例待补齐：{selected.demo_pending_reason}</InfoBar>}
          {selected.has_demo && <section className="vc-knowledge-detail-section"><h3>{selected.source === 'system' ? '技法演示' : '剪辑效果示例'}</h3><DemoPlayer id={selected.id} demos={selected.demos?.length ? selected.demos : [{ variant: 'example', label: selected.source === 'system' ? '教学演示' : '原片示例' }]} initiallyOpen={demoRequested} /></section>}
          <section className="vc-knowledge-detail-section"><h3>技法说明</h3><p>{selected.content || '暂无说明'}</p></section>
          {selected.best_when && <section className="vc-knowledge-detail-section"><h3>适用场景</h3><p>{selected.best_when}</p></section>}
          {selected.structured_data?.effectiveness && <section className="vc-knowledge-detail-section"><h3>效果与依据</h3><p>{selected.structured_data.effectiveness}</p></section>}
          {selected.structured_data?.connection_to_body && <section className="vc-knowledge-detail-section"><h3>如何衔接正文</h3><p>{selected.structured_data.connection_to_body}</p></section>}
          {selected.type === 'effect_type' && selected.structured_data?.evidence?.length > 0 && <section className="vc-knowledge-detail-section"><h3>原片中的应用位置 · {selected.structured_data.category || '特效'}</h3><div className="vc-knowledge-segments">{selected.structured_data.evidence.map((evidence, index) => <details key={evidence.id || index}><summary><span>{String(index + 1).padStart(2, '0')}</span><strong>{evidence.subject || selected.title}</strong><small>{Number(evidence.start_time).toFixed(2)}–{Number(evidence.end_time).toFixed(2)}s</small></summary><p>{evidence.parameters?.style || evidence.parameters?.outline_style || evidence.parameters?.border_style || '观察这段画面中的效果与主体关系。'}{evidence.position && Object.keys(evidence.position).length > 0 ? ` · 锚点 ${Math.round(Number(evidence.position.x || 0) * 100)}%、${Math.round(Number(evidence.position.y || 0) * 100)}%` : ''}{evidence.motion_path?.length > 0 ? ` · ${evidence.motion_path.length} 个运动路径节点` : ''}{evidence.mask_mode === 'subject_cutout' ? ' · 需要主体抠像' : ''}</p></details>)}</div></section>}
          {selected.structured_data?.script_structure?.length > 0 && <section className="vc-knowledge-detail-section"><h3>段落用法</h3><div className="vc-knowledge-segments">{selected.structured_data.script_structure.map((segment, index) => <details key={index}><summary><span>{String(index + 1).padStart(2, '0')}</span><strong>{segment.purpose}</strong><small>{segment.duration_hint ? `${segment.duration_hint}s` : ''}</small></summary><p>{segment.content_summary}</p></details>)}</div></section>}
          <section className="vc-knowledge-detail-section"><h3>参考来源</h3><p>{selected.source_summary || (selected.source === 'user' ? '个人提炼' : '系统内置技法')}</p>
            {selected.derivation?.source_gene_id && <Link className="vc-library-source-link" to={`/genes/${selected.derivation.source_gene_id}`}>查看来源视频与完整分析 <ArrowUpRight size={14} /></Link>}
          </section>
          {selected.tags?.length > 0 && <details className="vc-library-extra"><summary>全部标签 · {selected.tags.length}</summary><div>{selected.tags.map((tag, index) => <Badge key={index} color="gray">{tag}</Badge>)}</div></details>}
        </LibraryDetail>
      )}
    </div>
  )
}
