import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity,
  BarChart3,
  BookOpen,
  Bot,
  Clapperboard,
  Command,
  Dna,
  FolderOpen,
  LayoutDashboard,
  LogOut,
  Menu,
  PlaySquare,
  Settings,
  Sparkles,
  X,
} from 'lucide-react'
import { useAuth } from '../context/auth-context.js'

const NAV_ITEMS = [
  { to: '/', label: '工作台', hint: '今日概览', icon: LayoutDashboard, end: true },
  { to: '/assistant', label: '智能助手', hint: '自然语言执行', icon: Bot },
  { to: '/projects', label: '项目', hint: '创作与任务', icon: FolderOpen },
  { to: '/genes', label: '基因库', hint: '爆款结构', icon: Dna },
  { to: '/knowledge', label: '知识库', hint: '剪辑经验', icon: BookOpen },
  { to: '/insights', label: '统计洞察', hint: '质量与效率', icon: BarChart3 },
  { to: '/works', label: '作品集', hint: '参考与成片', icon: PlaySquare },
  { to: '/settings', label: '设置', hint: '模型与系统', icon: Settings },
]

const PAGE_META = [
  { match: /^\/$/, title: '创作工作区', description: '从爆款结构到最终成片的一站式工作流' },
  { match: /^\/assistant/, title: 'AI 协作中心', description: '用自然语言推进分析、规划与渲染' },
  { match: /^\/projects\/\d+/, title: '项目工作室', description: '管理参考视频、创作素材与生成任务' },
  { match: /^\/projects/, title: '项目空间', description: '组织每一次视频结构迁移' },
  { match: /^\/tasks/, title: '任务监控', description: '跟踪多智能体流水线的实时状态' },
  { match: /^\/genes\/\d+/, title: '基因详情', description: '查看参考视频的结构与爆款机制' },
  { match: /^\/genes/, title: '视频基因库', description: '沉淀可复用的结构、节奏与视觉手法' },
  { match: /^\/knowledge/, title: '剪辑知识库', description: '管理系统可调用的专业经验' },
  { match: /^\/insights/, title: '数据洞察', description: '观察生成质量与运行效率' },
  { match: /^\/works/, title: '作品陈列室', description: '对照参考视频检查最终迁移效果' },
  { match: /^\/settings/, title: '系统设置', description: '管理模型连接和运行参数' },
]

function BrandMark({ compact = false }) {
  return (
    <div className={`vc-brand-mark ${compact ? 'is-compact' : ''}`} aria-hidden="true">
      <Clapperboard size={compact ? 17 : 19} />
    </div>
  )
}

function SidebarContent({ onNavigate, serviceStatus }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="vc-sidebar-inner">
      <button className="vc-brand" type="button" onClick={() => { navigate('/'); onNavigate?.() }}>
        <BrandMark />
        <span className="vc-brand-copy">
          <strong>Video Claw</strong>
          <small>AI Editing Studio</small>
        </span>
      </button>

      <nav className="vc-primary-nav" aria-label="主导航">
        <div className="vc-nav-label">Workspace</div>
        {NAV_ITEMS.map(({ to, label, hint, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) => `vc-nav-item ${isActive ? 'is-active' : ''}`}
          >
            {({ isActive }) => (
              <>
                <span className="vc-nav-icon"><Icon size={17} /></span>
                <span className="vc-nav-copy">
                  <strong>{label}</strong>
                  <small>{hint}</small>
                </span>
                {isActive && <i className="vc-nav-indicator" />}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="vc-sidebar-bottom">
        <div className={`vc-runtime-card is-${serviceStatus}`}>
          <span className="vc-runtime-head"><Activity size={13} /><i /> 系统状态</span>
          <strong>{serviceStatus === 'online' ? '后端服务可连接' : serviceStatus === 'offline' ? '后端服务暂不可用' : '正在检查连接'}</strong>
          <small>{serviceStatus === 'online' ? '可以继续管理项目与任务' : '连接状态每 30 秒更新'}</small>
        </div>
        <div className="vc-profile-chip">
          <span className="vc-profile-avatar">{(user?.username || '?').slice(0, 2).toUpperCase()}</span>
          <span>
            <strong>{user?.username}</strong>
            <small>创作者工作区</small>
          </span>
          <button type="button" onClick={logout} title="退出登录" aria-label="退出登录">
            <LogOut size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const [serviceStatus, setServiceStatus] = useState('checking')
  const location = useLocation()
  const navigate = useNavigate()
  const { user } = useAuth()
  const page = PAGE_META.find((item) => item.match.test(location.pathname)) || PAGE_META[0]

  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 721px)')
    const closeDrawer = () => { if (desktop.matches) setMobileOpen(false) }
    desktop.addEventListener('change', closeDrawer)
    return () => desktop.removeEventListener('change', closeDrawer)
  }, [])

  useEffect(() => {
    let stopped = false
    let controller
    const checkHealth = async () => {
      controller?.abort()
      controller = new AbortController()
      const timeout = window.setTimeout(() => controller.abort(), 5000)
      try {
        const response = await fetch('/api/health', { signal: controller.signal, cache: 'no-store' })
        const data = response.ok ? await response.json() : null
        if (!stopped) setServiceStatus(data?.status === 'ok' ? 'online' : 'offline')
      } catch {
        if (!stopped) setServiceStatus('offline')
      } finally {
        window.clearTimeout(timeout)
      }
    }
    checkHealth()
    const interval = window.setInterval(checkHealth, 30000)
    return () => { stopped = true; controller?.abort(); window.clearInterval(interval) }
  }, [])

  useEffect(() => {
    if (!mobileOpen) return
    const previousFocus = document.activeElement
    const dialog = document.getElementById('mobile-navigation')
    const focusable = Array.from(dialog.querySelectorAll('a, button')).filter((element) => element.tabIndex >= 0 && element.getClientRects().length)
    focusable[0]?.focus()
    const handleKey = (event) => {
      if (event.key === 'Escape') setMobileOpen(false)
      if (event.key !== 'Tab') return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    document.addEventListener('keydown', handleKey)
    return () => { document.removeEventListener('keydown', handleKey); previousFocus?.focus() }
  }, [mobileOpen])

  useEffect(() => {
    const handleShortcut = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        navigate('/assistant')
      }
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [navigate])

  return (
    <div className="vc-app-shell">
      <aside className="vc-app-sidebar">
        <SidebarContent serviceStatus={serviceStatus} />
      </aside>

      <div className="vc-mobile-topbar">
        <button type="button" className="vc-mobile-brand" onClick={() => navigate('/')}>
          <BrandMark compact />
          <span>Video Claw</span>
        </button>
        <button
          type="button"
          onClick={() => setMobileOpen((value) => !value)}
          className="vc-mobile-menu"
          aria-label={mobileOpen ? '关闭导航' : '打开导航'}
          aria-expanded={mobileOpen}
          aria-controls={mobileOpen ? 'mobile-navigation' : undefined}
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {mobileOpen && (
        <div className="vc-mobile-drawer" role="dialog" aria-modal="true" aria-label="导航菜单" id="mobile-navigation">
          <button className="vc-mobile-backdrop" type="button" tabIndex={-1} onClick={() => setMobileOpen(false)} aria-label="关闭导航" />
          <aside>
            <button type="button" className="vc-drawer-close" onClick={() => setMobileOpen(false)} aria-label="关闭导航菜单"><X size={18} /></button>
            <SidebarContent serviceStatus={serviceStatus} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <main className="vc-app-main">
        <header className="vc-app-topbar">
          <div>
            <span className="vc-topbar-kicker">Video Intelligence Platform</span>
            <h1>{page.title}</h1>
            <p>{page.description}</p>
          </div>
          <div className="vc-topbar-actions">
            <button className="vc-command-button" type="button" onClick={() => navigate('/assistant')}>
              <Sparkles size={15} /> 召唤助手 <kbd><Command size={10} /> K</kbd>
            </button>
            <span className={`vc-service-pill is-${serviceStatus}`} role="status"><i />{serviceStatus === 'online' ? '后端已连接' : serviceStatus === 'offline' ? '后端未连接' : '检查连接中'}</span>
            <button className="vc-topbar-avatar" type="button" onClick={() => navigate('/settings')} title="打开设置">
              {(user?.username || '?').slice(0, 2).toUpperCase()}
            </button>
          </div>
        </header>
        <div className="vc-page-content">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
