import { useEffect, useMemo, useState } from 'react'
import {
  BrainCircuit,
  Check,
  CircleAlert,
  Cpu,
  Edit3,
  Eye,
  KeyRound,
  Plus,
  Power,
  Server,
  ShieldCheck,
  Trash2,
  X,
  Zap,
} from 'lucide-react'
import {
  createModel,
  deleteModel,
  listModels,
  setDefaultModel,
  testModel,
  updateModel,
} from '../api.js'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  InfoBar,
  SectionHeader,
  SelectInput,
  TextInput,
} from '../components/ui.jsx'

const PROVIDERS = [
  { key: 'zhipu', label: '智谱 AI', short: 'GLM', color: '#00d4ff', endpointUrl: 'https://open.bigmodel.cn/api/paas/v4', modelId: 'glm-4.6v-flash', supportsVision: true },
  { key: 'deepseek', label: 'DeepSeek', short: 'DS', color: '#7c5cfc', endpointUrl: 'https://api.deepseek.com', modelId: 'deepseek-chat', supportsVision: false },
  { key: 'moonshot', label: 'Moonshot / Kimi', short: 'K', color: '#34d399', endpointUrl: 'https://api.moonshot.cn/v1', modelId: 'kimi-2.6', supportsVision: false },
  { key: 'openai', label: 'OpenAI 兼容', short: 'AI', color: '#fbbf24', endpointUrl: 'https://api.openai.com/v1', modelId: '', supportsVision: false },
  { key: 'custom', label: '自定义服务', short: '自', color: '#f472b6', endpointUrl: '', modelId: '', supportsVision: false },
]

const EMPTY_FORM = {
  provider: 'zhipu', display_name: 'GLM 视觉分析', model_id: 'glm-4.6v-flash',
  endpoint_url: 'https://open.bigmodel.cn/api/paas/v4', endpoint_mode: 'base_url',
  api_format: 'openai_chat_completions', api_key: '', supports_vision: true,
  enabled: true, use_for_vision: true, use_for_text: false,
  input_price_per_million: '', output_price_per_million: '', cached_input_price_per_million: '', price_currency: 'CNY',
}

function providerMeta(key) {
  return PROVIDERS.find((item) => item.key === key) || PROVIDERS.at(-1)
}

function errorText(error, fallback) {
  const detail = error.response?.data?.detail
  if (Array.isArray(detail)) return detail[0]?.msg || fallback
  return detail || fallback
}

function ProviderMark({ provider, size = 'md' }) {
  const meta = providerMeta(provider)
  const sizeClass = size === 'lg' ? 'h-11 w-11 text-sm' : 'h-9 w-9 text-xs'
  return (
    <span className={`${sizeClass} inline-flex shrink-0 items-center justify-center rounded-xl border font-bold`}
      style={{ color: meta.color, borderColor: `${meta.color}35`, background: `${meta.color}12` }}>
      {meta.short}
    </span>
  )
}

function ModelCard({ model, onEdit, onDelete, onToggle, onSetDefault }) {
  return (
    <Card className={`p-4 ${model.enabled ? '' : 'opacity-60'}`}>
      <div className="flex items-start gap-3">
        <ProviderMark provider={model.provider} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-[#e8e8f0]">{model.display_name}</h3>
            {!model.enabled && <Badge color="gray">已停用</Badge>}
            {model.last_test_status === 'success' && <Badge color="green">已验证</Badge>}
            {model.last_test_status === 'failed' && <Badge color="red">验证失败</Badge>}
          </div>
          <p className="mt-1 truncate font-mono text-xs text-[#8888a8]">{model.model_id}</p>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" title={model.enabled ? '停用' : '启用'} onClick={() => onToggle(model)} className="rounded-lg p-2 text-[#6f6f91] transition hover:bg-[#24243a] hover:text-white"><Power size={15} /></button>
          <button type="button" title="编辑" onClick={() => onEdit(model)} className="rounded-lg p-2 text-[#6f6f91] transition hover:bg-[#24243a] hover:text-white"><Edit3 size={15} /></button>
          <button type="button" title="删除" onClick={() => onDelete(model)} className="rounded-lg p-2 text-[#6f6f91] transition hover:bg-[rgba(248,113,113,0.08)] hover:text-[#f87171]"><Trash2 size={15} /></button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <button type="button" disabled={!model.enabled || !model.supports_vision} onClick={() => onSetDefault(model, 'vision')}
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition ${model.is_default_vision ? 'border-[rgba(0,212,255,0.35)] bg-[rgba(0,212,255,0.08)] text-[#66e0ff]' : 'border-[#2a2a42] text-[#777795] hover:border-[#3b3b5c] disabled:cursor-not-allowed disabled:opacity-35'}`}>
          <Eye size={14} /><span className="flex-1">视觉分析</span>{model.is_default_vision && <Check size={13} />}
        </button>
        <button type="button" disabled={!model.enabled} onClick={() => onSetDefault(model, 'text')}
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition ${model.is_default_text ? 'border-[rgba(124,92,252,0.4)] bg-[rgba(124,92,252,0.1)] text-[#b49aff]' : 'border-[#2a2a42] text-[#777795] hover:border-[#3b3b5c] disabled:cursor-not-allowed disabled:opacity-35'}`}>
          <BrainCircuit size={14} /><span className="flex-1">方案生成</span>{model.is_default_text && <Check size={13} />}
        </button>
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-[#24243a] pt-3 text-[11px] text-[#62627e]">
        <span className="truncate pr-3">{model.endpoint_url}</span>
        <span className="shrink-0 font-mono">{model.masked_api_key}</span>
      </div>
    </Card>
  )
}

export default function Settings() {
  const [models, setModels] = useState([])
  const [panelOpen, setPanelOpen] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [message, setMessage] = useState(null)
  const [testResult, setTestResult] = useState(null)

  const activeModels = useMemo(() => models.filter((item) => item.enabled), [models])
  const visionModel = activeModels.find((item) => item.is_default_vision)
  const textModel = activeModels.find((item) => item.is_default_text)

  const fetchModels = async () => {
    try {
      const response = await listModels()
      setModels(response.data)
    } catch (error) {
      setMessage({ type: 'error', text: errorText(error, '模型配置加载失败') })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchModels() }, [])

  const openCreate = () => {
    setEditingId(null); setForm({ ...EMPTY_FORM }); setTestResult(null); setPanelOpen(true)
  }

  const openEdit = (model) => {
    setEditingId(model.id)
    setForm({
      provider: model.provider, display_name: model.display_name, model_id: model.model_id,
      endpoint_url: model.endpoint_url, endpoint_mode: model.endpoint_mode,
      api_format: model.api_format, api_key: '', supports_vision: model.supports_vision,
      enabled: model.enabled, use_for_vision: model.is_default_vision, use_for_text: model.is_default_text,
      input_price_per_million: model.input_price_per_million ?? '', output_price_per_million: model.output_price_per_million ?? '',
      cached_input_price_per_million: model.cached_input_price_per_million ?? '', price_currency: model.price_currency || 'CNY',
    })
    setTestResult(null); setPanelOpen(true)
  }

  const changeProvider = (provider) => {
    const preset = providerMeta(provider)
    setForm((current) => ({
      ...current, provider, display_name: provider === 'custom' ? '' : preset.label,
      endpoint_url: preset.endpointUrl, model_id: preset.modelId,
      supports_vision: preset.supportsVision, use_for_vision: preset.supportsVision,
      use_for_text: !preset.supportsVision,
      input_price_per_million: '', output_price_per_million: '', cached_input_price_per_million: '',
    }))
    setTestResult(null)
  }

  const patchForm = (patch) => { setForm((current) => ({ ...current, ...patch })); setTestResult(null) }

  const validateForm = () => {
    if (!form.display_name.trim()) return '请填写模型展示名称'
    if (!form.model_id.trim()) return '请填写服务商提供的模型 ID'
    if (!form.endpoint_url.trim()) return '请填写模型请求地址'
    if (!/^https?:\/\//i.test(form.endpoint_url.trim())) return '请求地址需要以 http:// 或 https:// 开头'
    if (form.use_for_vision && !form.supports_vision) return '视觉分析模型必须开启图片输入能力'
    if ((form.input_price_per_million === '') !== (form.output_price_per_million === '')) return '请同时填写输入价格和输出价格，或同时留空'
    return null
  }

  const handleTest = async () => {
    const validation = validateForm()
    if (validation) { setTestResult({ success: false, message: validation }); return }
    setTesting(true); setTestResult(null)
    try {
      const response = await testModel({
        provider: form.provider, model_id: form.model_id.trim(), endpoint_url: form.endpoint_url.trim(),
        endpoint_mode: form.endpoint_mode, api_format: form.api_format,
        api_key: form.api_key.trim() || null, model_config_id: editingId,
      })
      setTestResult(response.data)
    } catch (error) {
      setTestResult({ success: false, message: errorText(error, '连接测试失败') })
    } finally { setTesting(false) }
  }

  const handleSave = async (event) => {
    event.preventDefault()
    const validation = validateForm()
    if (validation) { setTestResult({ success: false, message: validation }); return }
    const localEndpoint = /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(form.endpoint_url)
    if (!editingId && !form.api_key.trim() && !localEndpoint) {
      setTestResult({ success: false, message: '远程模型请填写 API Key；本地兼容服务可以留空' }); return
    }
    setSaving(true); setMessage(null)
    try {
      const payload = { ...form, display_name: form.display_name.trim(), model_id: form.model_id.trim(), endpoint_url: form.endpoint_url.trim(), api_key: form.api_key.trim() }
      for (const key of ['input_price_per_million', 'output_price_per_million', 'cached_input_price_per_million']) payload[key] = form[key] === '' ? null : Number(form[key])
      if (editingId) {
        delete payload.use_for_vision; delete payload.use_for_text
        await updateModel(editingId, payload)
      } else await createModel(payload)
      await fetchModels(); setPanelOpen(false)
      setMessage({ type: 'success', text: editingId ? '模型配置已更新' : '模型已添加，可以用于任务了' })
    } catch (error) {
      setTestResult({ success: false, message: errorText(error, '模型保存失败') })
    } finally { setSaving(false) }
  }

  const handleDelete = async (model) => {
    if (!confirm(`确定删除“${model.display_name}”吗？`)) return
    try { await deleteModel(model.id); await fetchModels(); setMessage({ type: 'success', text: '模型配置已删除' }) }
    catch (error) { setMessage({ type: 'error', text: errorText(error, '删除失败') }) }
  }

  const handleToggle = async (model) => {
    try { await updateModel(model.id, { enabled: !model.enabled }); await fetchModels() }
    catch (error) { setMessage({ type: 'error', text: errorText(error, '状态更新失败') }) }
  }

  const handleSetDefault = async (model, purpose) => {
    if ((purpose === 'vision' && model.is_default_vision) || (purpose === 'text' && model.is_default_text)) return
    try {
      await setDefaultModel(model.id, purpose); await fetchModels()
      setMessage({ type: 'success', text: purpose === 'vision' ? '视觉分析模型已切换' : '方案生成模型已切换' })
    } catch (error) { setMessage({ type: 'error', text: errorText(error, '默认模型切换失败') }) }
  }

  return (
    <div className="max-w-6xl">
      <SectionHeader title="模型与 API" description="接入你自己的模型服务，并指定它在视频工作流中的职责。" actions={<Button icon={Plus} onClick={openCreate}>添加模型</Button>} />
      {message && <div className="mb-5"><InfoBar type={message.type}>{message.text}</InfoBar></div>}

      <div className="mb-6 grid gap-3 md:grid-cols-2">
        <div className={`rounded-xl border p-4 ${visionModel ? 'border-[rgba(0,212,255,0.2)] bg-[rgba(0,212,255,0.05)]' : 'border-[rgba(251,191,36,0.25)] bg-[rgba(251,191,36,0.05)]'}`}>
          <div className="flex items-center gap-3"><span className="rounded-lg bg-[rgba(0,212,255,0.1)] p-2 text-[#66e0ff]"><Eye size={18} /></span><div><p className="text-sm font-medium text-[#d8d8e8]">视觉分析模型</p><p className="mt-0.5 text-xs text-[#777795]">{visionModel?.display_name || '未配置，无法分析视频画面和图片素材'}</p></div></div>
        </div>
        <div className={`rounded-xl border p-4 ${textModel ? 'border-[rgba(124,92,252,0.25)] bg-[rgba(124,92,252,0.06)]' : 'border-[rgba(251,191,36,0.25)] bg-[rgba(251,191,36,0.05)]'}`}>
          <div className="flex items-center gap-3"><span className="rounded-lg bg-[rgba(124,92,252,0.12)] p-2 text-[#b49aff]"><BrainCircuit size={18} /></span><div><p className="text-sm font-medium text-[#d8d8e8]">方案生成模型</p><p className="mt-0.5 text-xs text-[#777795]">{textModel?.display_name || '未配置，多智能体方案生成不可用'}</p></div></div>
        </div>
      </div>

      <div className="mb-4 flex items-center justify-between"><div><h2 className="text-sm font-semibold text-[#d8d8e8]">已添加的模型</h2><p className="mt-1 text-xs text-[#666681]">密钥不会在页面或查询接口中显示；编辑时留空代表继续使用原密钥。</p></div><Badge color="gray">{models.length} 个配置</Badge></div>
      {loading ? <Card className="p-8 text-center text-sm text-[#777795]">正在加载模型配置…</Card> : models.length === 0 ? (
        <Card><EmptyState icon={Cpu} title="还没有模型配置" description="至少添加一个支持图片输入的模型，才能开始视频分析。"><Button icon={Plus} onClick={openCreate}>添加第一个模型</Button></EmptyState></Card>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">{models.map((model) => <ModelCard key={model.id} model={model} onEdit={openEdit} onDelete={handleDelete} onToggle={handleToggle} onSetDefault={handleSetDefault} />)}</div>
      )}

      <Card className="mt-6 flex gap-3 p-4"><ShieldCheck size={18} className="mt-0.5 shrink-0 text-[#6ee7b7]" /><div className="text-xs leading-5 text-[#777795]"><p className="font-medium text-[#a8a8bd]">当前支持 OpenAI Chat Completions 兼容接口</p><p>可接入 GLM、DeepSeek、Kimi、OpenAI 兼容网关和本地服务。Anthropic Messages 协议暂未接入，避免出现“保存成功但工作流不能调用”的假配置。</p></div></Card>

      {panelOpen && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm" onMouseDown={() => setPanelOpen(false)}>
          <div className="h-full w-full max-w-[560px] overflow-y-auto border-l border-[#2a2a42] bg-[#11111b] shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
            <form onSubmit={handleSave}>
              <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[#25253a] bg-[rgba(17,17,27,0.95)] px-6 py-4 backdrop-blur-xl"><div><h2 className="text-base font-semibold text-white">{editingId ? '编辑模型' : '添加模型'}</h2><p className="mt-0.5 text-xs text-[#666681]">配置将只归属于当前登录账号</p></div><button type="button" onClick={() => setPanelOpen(false)} className="rounded-lg p-2 text-[#777795] hover:bg-[#24243a] hover:text-white"><X size={18} /></button></div>
              <div className="space-y-6 p-6">
                <section>
                  <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#777795]"><Server size={14} /> 服务商</div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{PROVIDERS.map((provider) => (
                    <button type="button" key={provider.key} onClick={() => changeProvider(provider.key)} className={`flex items-center gap-2 rounded-xl border p-3 text-left text-xs transition ${form.provider === provider.key ? 'border-[#7c5cfc] bg-[rgba(124,92,252,0.1)] text-white' : 'border-[#2a2a42] text-[#8888a8] hover:border-[#3a3a58] hover:bg-[#191926]'}`}><ProviderMark provider={provider.key} /><span>{provider.label}</span></button>
                  ))}</div>
                </section>
                <section className="space-y-4">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#777795]"><Cpu size={14} /> 基础配置</div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="展示名称"><TextInput value={form.display_name} onChange={(event) => patchForm({ display_name: event.target.value })} placeholder="例如：GLM 视觉分析" /></Field>
                    <Field label="模型 ID" hint="必须与服务商控制台中的 ID 完全一致"><TextInput value={form.model_id} onChange={(event) => patchForm({ model_id: event.target.value })} placeholder="例如：glm-4.6v-flash" /></Field>
                  </div>
                  <Field label={form.endpoint_mode === 'full_url' ? '完整请求 URL' : 'Base URL'} hint={form.endpoint_mode === 'full_url' ? '直接请求这个地址' : '系统会自动拼接 /chat/completions'}><TextInput value={form.endpoint_url} onChange={(event) => patchForm({ endpoint_url: event.target.value })} placeholder="https://api.example.com/v1" /></Field>
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-[#8888a8]"><input type="checkbox" checked={form.endpoint_mode === 'full_url'} onChange={(event) => patchForm({ endpoint_mode: event.target.checked ? 'full_url' : 'base_url' })} className="h-4 w-4 accent-[#7c5cfc]" />我填写的是完整的 /chat/completions 请求地址</label>
                  <Field label="API 格式"><SelectInput value={form.api_format} disabled><option value="openai_chat_completions">OpenAI Chat Completions</option></SelectInput></Field>
                  <Field label="API Key" hint={editingId ? '留空将继续使用已保存的密钥' : '本地无鉴权服务可以留空'}><div className="relative"><KeyRound size={15} className="absolute left-3 top-2.5 text-[#5f5f7c]" /><TextInput type="password" autoComplete="new-password" value={form.api_key} onChange={(event) => patchForm({ api_key: event.target.value })} style={{ paddingLeft: '2.25rem' }} placeholder={editingId ? '••••••••（保持不变）' : '输入服务商 API Key'} /></div></Field>
                </section>
                <section className="space-y-3">
                  <div className="text-xs font-semibold text-[#777795]">费用估算（每百万 Token）</div>
                  <p className="text-xs leading-5 text-[#777795]">按你的服务商或网关实际单价填写，同时填写输入和输出价才会启用。留空时，仅官方 DeepSeek Flash / V4 Pro 使用官方峰时参考价；其他模型显示未计价。单价按调用时保存，不回算历史账单。</p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="币种"><SelectInput value={form.price_currency} onChange={(event) => patchForm({ price_currency: event.target.value })}><option value="CNY">人民币 CNY</option><option value="USD">美元 USD</option></SelectInput></Field>
                    <Field label="输入价格"><TextInput type="number" min="0" step="any" value={form.input_price_per_million} onChange={(event) => patchForm({ input_price_per_million: event.target.value })} placeholder="未配置" /></Field>
                    <Field label="输出价格"><TextInput type="number" min="0" step="any" value={form.output_price_per_million} onChange={(event) => patchForm({ output_price_per_million: event.target.value })} placeholder="未配置" /></Field>
                    <Field label="缓存命中输入价（可选）"><TextInput type="number" min="0" step="any" value={form.cached_input_price_per_million} onChange={(event) => patchForm({ cached_input_price_per_million: event.target.value })} placeholder="留空按普通输入价估算" /></Field>
                  </div>
                </section>
                <section className="space-y-3">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#777795]"><Zap size={14} /> 能力与用途</div>
                  <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-[#2a2a42] bg-[#171723] p-3"><input type="checkbox" checked={form.supports_vision} onChange={(event) => patchForm({ supports_vision: event.target.checked, use_for_vision: event.target.checked && form.use_for_vision })} className="mt-0.5 h-4 w-4 accent-[#00d4ff]" /><div><p className="text-sm text-[#c8c8dc]">支持图片输入</p><p className="mt-0.5 text-xs text-[#666681]">只有模型本身具备视觉能力时才开启</p></div></label>
                  {!editingId && <div className="grid grid-cols-2 gap-2">
                    <label className={`flex cursor-pointer items-center gap-2 rounded-xl border p-3 text-xs ${form.use_for_vision ? 'border-[rgba(0,212,255,0.3)] bg-[rgba(0,212,255,0.07)] text-[#66e0ff]' : 'border-[#2a2a42] text-[#777795]'}`}><input type="checkbox" disabled={!form.supports_vision} checked={form.use_for_vision} onChange={(event) => patchForm({ use_for_vision: event.target.checked })} className="h-4 w-4 accent-[#00d4ff]" /><Eye size={14} /> 设为视觉分析模型</label>
                    <label className={`flex cursor-pointer items-center gap-2 rounded-xl border p-3 text-xs ${form.use_for_text ? 'border-[rgba(124,92,252,0.35)] bg-[rgba(124,92,252,0.08)] text-[#b49aff]' : 'border-[#2a2a42] text-[#777795]'}`}><input type="checkbox" checked={form.use_for_text} onChange={(event) => patchForm({ use_for_text: event.target.checked })} className="h-4 w-4 accent-[#7c5cfc]" /><BrainCircuit size={14} /> 设为方案生成模型</label>
                  </div>}
                </section>
                {testResult && <div className={`flex gap-2 rounded-xl border p-3 text-xs ${testResult.success ? 'border-[rgba(52,211,153,0.25)] bg-[rgba(52,211,153,0.07)] text-[#6ee7b7]' : 'border-[rgba(248,113,113,0.25)] bg-[rgba(248,113,113,0.07)] text-[#fca5a5]'}`}>{testResult.success ? <ShieldCheck size={16} className="shrink-0" /> : <CircleAlert size={16} className="shrink-0" />}<span>{testResult.message}</span></div>}
              </div>
              <div className="sticky bottom-0 flex items-center justify-between border-t border-[#25253a] bg-[rgba(17,17,27,0.96)] px-6 py-4 backdrop-blur-xl"><Button type="button" variant="secondary" icon={Zap} loading={testing} onClick={handleTest}>测试连接</Button><div className="flex gap-2"><Button type="button" variant="ghost" onClick={() => setPanelOpen(false)}>取消</Button><Button type="submit" loading={saving}>{editingId ? '保存更改' : '添加模型'}</Button></div></div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
