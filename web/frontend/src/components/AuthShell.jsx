import { Check, Clapperboard, Film, Layers3, Sparkles } from 'lucide-react'

const FEATURES = [
  '解析镜头节奏与爆款机制',
  '协调多智能体完成端到端创作',
  '并排复审参考视频与生成成片',
]

export default function AuthShell({ children }) {
  return (
    <main className="vc-auth-shell">
      <section className="vc-auth-brand">
        <div className="vc-auth-brand-head">
          <span><Clapperboard size={20} /></span>
          <strong>Video Claw</strong>
        </div>
        <div className="vc-auth-message">
          <span className="vc-auth-kicker"><Sparkles size={13} /> AI VIDEO CREATION</span>
          <h1>把爆款视频的<br />创作逻辑变成你的能力</h1>
          <p>看懂参考片、编排新素材、迁移剪辑语言，并把每一次生成沉淀成可复用的知识。</p>
          <div className="vc-auth-features">
            {FEATURES.map((feature) => <span key={feature}><Check size={13} />{feature}</span>)}
          </div>
        </div>
        <div className="vc-auth-art" aria-hidden="true">
          <div className="vc-auth-card card-one"><Film size={19} /><span>Reference</span><i /></div>
          <div className="vc-auth-card card-two"><Layers3 size={19} /><span>Structure</span><i /></div>
          <div className="vc-auth-card card-three"><Sparkles size={19} /><span>Creation</span><i /></div>
        </div>
        <small className="vc-auth-foot">VIDEO INTELLIGENCE PLATFORM · 2026</small>
      </section>
      <section className="vc-auth-action">
        <div className="vc-auth-mobile-brand"><Clapperboard size={18} /><strong>Video Claw</strong></div>
        {children}
      </section>
    </main>
  )
}
