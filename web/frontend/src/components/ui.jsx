import { ArrowLeft, Loader2 } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'

/* ---------- Button ---------- */
const btnBase =
  'inline-flex items-center justify-center gap-2 font-medium transition-all duration-200 ' +
  'disabled:opacity-40 disabled:cursor-not-allowed select-none cursor-pointer'

const btnSizes = {
  sm: 'text-xs px-3 py-1.5 rounded-[9px]',
  md: 'text-sm px-4 py-2 rounded-[10px]',
  lg: 'text-sm px-5 py-2.5 rounded-[11px]',
}

const btnVariants = {
  primary:
    'bg-[#7154df] text-white hover:bg-[#6246ce] shadow-[0_8px_20px_rgba(101,74,205,0.20)] hover:shadow-[0_10px_24px_rgba(101,74,205,0.28)]',
  secondary:
    'bg-white text-[#40485e] border border-[#dde1eb] shadow-sm hover:bg-[#f7f8fc] hover:text-[#20243a] hover:border-[#cbd1de]',
  danger:
    'bg-white text-[#c2414d] border border-[rgba(194,65,77,0.22)] hover:bg-[#fff5f5] hover:border-[rgba(194,65,77,0.36)]',
  ghost:
    'text-[#667085] hover:bg-[#f0f2f8] hover:text-[#20243a]',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon: Icon,
  children,
  className = '',
  disabled,
  ...props
}) {
  return (
    <button
      className={`${btnBase} ${btnSizes[size]} ${btnVariants[variant]} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <Loader2 size={16} className="animate-spin" />
      ) : (
        Icon && <Icon size={16} />
      )}
      {children}
    </button>
  )
}

/* ---------- Card ---------- */
export function Card({ className = '', hover = false, ...props }) {
  return (
    <div
      className={
        `bg-white rounded-[18px] border border-[rgba(45,35,69,0.08)] shadow-[var(--shadow-sm)] ` +
        `${hover ? 'transition-all duration-300 hover:shadow-[var(--shadow-md)] hover:-translate-y-0.5 hover:border-[#d8cff5]' : ''} ${className}`
      }
      {...props}
    />
  )
}

/* ---------- Badge ---------- */
const badgeColors = {
  gray:   'bg-[#f1eef3] text-[#766e80]',
  indigo: 'bg-[#eee9ff] text-[#654cc2]',
  blue:   'bg-[#e5f5f8] text-[#257e90]',
  green:  'bg-[#e8f7f0] text-[#267e5d]',
  red:    'bg-[#fff0f1] text-[#b9505c]',
  amber:  'bg-[#fff4dd] text-[#9a6b22]',
  purple: 'bg-[#f3eaff] text-[#7951ad]',
}

export function Badge({ color = 'gray', className = '', children }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${badgeColors[color]} ${className}`}
    >
      {children}
    </span>
  )
}

/* ---------- StatusPill ---------- */
const statusMeta = {
  pending:   { label: '排队中', dot: 'bg-[#9b94a4]', text: 'text-[#766e80]', bg: 'bg-[#f1eef3]' },
  running:   { label: '运行中', dot: 'bg-[#7154df]', text: 'text-[#654cc2]', bg: 'bg-[#eee9ff]' },
  awaiting_confirmation: { label: '等待确认', dot: 'bg-[#d39c45]', text: 'text-[#9a6b22]', bg: 'bg-[#fff4dd]' },
  success:   { label: '成功', dot: 'bg-[#32ad7c]', text: 'text-[#267e5d]', bg: 'bg-[#e8f7f0]' },
  failed:    { label: '失败', dot: 'bg-[#d95c6a]', text: 'text-[#b9505c]', bg: 'bg-[#fff0f1]' },
  cancelled: { label: '已取消', dot: 'bg-[#9b94a4]', text: 'text-[#766e80]', bg: 'bg-[#f1eef3]' },
}

export function StatusPill({ status }) {
  const meta = statusMeta[status] || statusMeta.pending
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${meta.bg} ${meta.text}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${meta.dot} ${status === 'running' ? 'vc-pulse-dot' : ''}`}
      />
      {meta.label}
    </span>
  )
}

/* ---------- ProgressBar ---------- */
export function ProgressBar({ value = 0, className = '' }) {
  return (
    <div className={`h-2 w-full overflow-hidden rounded-full bg-[#ebe7ee] ${className}`}>
      <div
        className="h-full rounded-full bg-gradient-to-r from-[#7154df] to-[#42a6b7] transition-all duration-500"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  )
}

/* ---------- EmptyState ---------- */
export function EmptyState({ icon: Icon, title, description, children }) {
  return (
    <div className="flex flex-col items-center justify-center py-14 text-center">
      {Icon && (
        <div className="mb-3 rounded-2xl bg-[#f1eef8] p-3.5">
          <Icon size={24} className="text-[#7154df]" />
        </div>
      )}
      <p className="text-sm font-medium text-[#494151]">{title}</p>
      {description && <p className="mt-1 text-sm text-[#8b8495]">{description}</p>}
      {children && <div className="mt-4">{children}</div>}
    </div>
  )
}

/* ---------- SectionHeader ---------- */
export function SectionHeader({ title, description, actions, backTo }) {
  const navigate = useNavigate()
  const location = useLocation()

  const handleBack = () => {
    // Keep the user's actual in-app path when possible. A direct link or a
    // refreshed detail page falls back to its owning list page.
    if (location.key !== 'default') {
      navigate(-1)
      return
    }
    navigate(backTo || '/')
  }

  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 items-start gap-3">
        {backTo && (
          <button
            type="button"
            onClick={handleBack}
            className="mt-0.5 inline-flex shrink-0 items-center gap-1.5 rounded-[10px] border border-[#e2dee7] bg-white px-2.5 py-1.5 text-xs font-medium text-[#766e80] shadow-sm transition-colors hover:border-[#cfc5eb] hover:bg-[#f7f4ff] hover:text-[#654cc2]"
            aria-label="返回上一页"
          >
            <ArrowLeft size={14} />
            返回
          </button>
        )}
        <div className="min-w-0">
          <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.16em] text-[#8d78c9]">Workspace</span>
          <h1 className="text-[26px] font-semibold tracking-[-0.035em] text-[#211d34]">{title}</h1>
          {description && <p className="mt-1 text-sm text-[#8b8495]">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

/* ---------- Field ---------- */
const inputCls =
  'w-full rounded-[10px] border border-[#ded9eb] bg-[#fcfbfd] px-3 py-2 text-sm text-[#332a4b] shadow-sm ' +
  'placeholder:text-[#a49dac] focus:border-[#8065de] focus:outline-none focus:ring-2 focus:ring-[rgba(113,84,223,0.14)] ' +
  'transition-colors duration-200'

export function Field({ label, hint, children, className = '' }) {
  return (
    <div className={className}>
      {label && (
        <label className="mb-1.5 block text-xs font-medium text-[#655e6e]">{label}</label>
      )}
      {children}
      {hint && <p className="mt-1 text-xs text-[#9991a1]">{hint}</p>}
    </div>
  )
}

export function TextInput(props) {
  return <input className={inputCls} {...props} />
}

export function SelectInput(props) {
  return <select className={`${inputCls} pr-8`} {...props} />
}

/* ---------- InfoBar ---------- */
const infoColors = {
  info:    'bg-[#eef8fa] text-[#257e90] border-[#cce9ee]',
  warn:    'bg-[#fff8e9] text-[#9a6b22] border-[#f1dfba]',
  error:   'bg-[#fff0f1] text-[#b9505c] border-[#f3cfd4]',
  success: 'bg-[#ecf8f3] text-[#267e5d] border-[#ccebdd]',
}

export function InfoBar({ type = 'info', children }) {
  return (
    <div className={`rounded-lg border px-3.5 py-2.5 text-sm ${infoColors[type]}`}>
      {children}
    </div>
  )
}
