import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  BookOpen,
  ChevronRight,
  Clapperboard,
  Dna,
  FolderOpen,
  Layers3,
  Play,
  PlaySquare,
  Sparkles,
  Upload,
  WandSparkles,
} from 'lucide-react'
import { getStats } from '../api.js'
import { Button, Card, StatusPill } from '../components/ui.jsx'

const STAT_CARDS = [
  { key: 'projects', label: '创作项目', detail: '结构迁移工作区', icon: FolderOpen, to: '/projects', tone: 'violet' },
  { key: 'genes', label: '视频基因', detail: '已提取结构资产', icon: Dna, to: '/genes', tone: 'coral' },
  { key: 'knowledge', label: '知识条目', detail: '可调用剪辑经验', icon: BookOpen, to: '/knowledge', tone: 'cyan' },
  { key: 'works', label: '生成成片', detail: '已交付作品', icon: PlaySquare, to: '/works', tone: 'green' },
]

const GUIDE_STEPS = [
  {
    icon: Dna,
    step: '01',
    title: '解析参考视频',
    desc: '提取 Hook、镜头节奏、转场、文字与声音设计，形成可复用视频基因。',
    to: '/genes',
  },
  {
    icon: Layers3,
    step: '02',
    title: '编排你的素材',
    desc: '建立项目并上传素材，Planner 会按照内容语义匹配镜头且避免重复使用。',
    to: '/projects',
  },
  {
    icon: WandSparkles,
    step: '03',
    title: '审查并生成',
    desc: '确认分镜后进入渲染，最终在作品集中并排检查参考片与生成片。',
    to: '/works',
  },
]

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    getStats()
      .then((res) => setStats(res.data))
      .catch(() => setStats({ projects: 0, genes: 0, knowledge: 0, works: 0, recent_tasks: [] }))
  }, [])

  if (!stats) {
    return <div className="py-16 text-center text-sm text-[#8b8495]">正在加载创作空间…</div>
  }

  return (
    <div className="vc-dashboard vc-fade-in">
      <section className="vc-dashboard-hero">
        <i className="vc-hero-orb vc-hero-orb-one" />
        <i className="vc-hero-orb vc-hero-orb-two" />
        <div className="vc-hero-copy">
          <span className="vc-hero-kicker"><Sparkles size={13} /> AI VIDEO WORKFLOW</span>
          <h2>让参考视频的<br />爆款结构真正落地</h2>
          <p>从视觉分析、视频基因、素材规划到成片复审，把一次生成变成可检查、可迭代的完整流程。</p>
          <div className="vc-hero-actions">
            <Button icon={Clapperboard} size="lg" onClick={() => navigate('/projects')}>开始新项目</Button>
            <button type="button" onClick={() => navigate('/genes')}><Upload size={15} /> 提取参考视频</button>
          </div>
        </div>
        <div className="vc-hero-preview" aria-hidden="true">
          <div className="vc-preview-window">
            <div className="vc-preview-bar"><i /><i /><i /><span>structure-map.vc</span></div>
            <div className="vc-preview-stage">
              <div className="vc-preview-play"><Play size={18} fill="currentColor" /></div>
              <span className="vc-preview-shot one" />
              <span className="vc-preview-shot two" />
              <span className="vc-preview-shot three" />
              <span className="vc-preview-timeline" />
            </div>
          </div>
        </div>
      </section>

      <section className="vc-metric-grid" aria-label="项目统计">
        {STAT_CARDS.map(({ key, label, detail, icon: Icon, to, tone }) => (
          <Link key={key} to={to} className="vc-metric-card">
            <span className={`vc-metric-icon tone-${tone}`}><Icon size={19} /></span>
            <span>
              <small>{label}</small>
              <strong>{stats[key]}</strong>
              <em>{detail}</em>
            </span>
            <ChevronRight size={15} />
          </Link>
        ))}
      </section>

      <div className="vc-dashboard-grid">
        <Card className="vc-recent-panel">
          <div className="vc-panel-heading">
            <div><span>RECENT ACTIVITY</span><h2>最近任务</h2></div>
            <Link to="/projects">全部项目 <ArrowRight size={13} /></Link>
          </div>
          {stats.recent_tasks.length === 0 ? (
            <div className="vc-recent-empty">
              <span><Clapperboard size={21} /></span>
              <div><strong>还没有任务记录</strong><p>创建项目、添加参考视频和素材后，从这里跟踪生成过程。</p></div>
              <Button size="sm" onClick={() => navigate('/projects')}>创建项目</Button>
            </div>
          ) : (
            <div className="vc-task-list">
              {stats.recent_tasks.map((task) => (
                <button key={task.id} type="button" onClick={() => navigate(`/tasks/${task.id}`)}>
                  <span className="vc-task-number">#{task.id}</span>
                  <span className="vc-task-copy"><strong>{task.project_name}</strong><small>生成进度 {task.progress}%</small></span>
                  <span className="vc-task-track"><i style={{ width: `${task.progress}%` }} /></span>
                  <StatusPill status={task.status} />
                  <ChevronRight size={15} />
                </button>
              ))}
            </div>
          )}
        </Card>

        <Card className="vc-flow-panel">
          <div className="vc-panel-heading">
            <div><span>WORKFLOW</span><h2>三步完成迁移</h2></div>
          </div>
          <div className="vc-flow-list">
            {GUIDE_STEPS.map(({ icon: Icon, step, title, desc, to }) => (
              <button key={step} type="button" onClick={() => navigate(to)}>
                <span className="vc-flow-icon"><Icon size={17} /></span>
                <span><small>{step}</small><strong>{title}</strong><p>{desc}</p></span>
                <ChevronRight size={15} />
              </button>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
