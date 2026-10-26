import { useEffect, useState } from 'react'
import { Activity, Coins, Hash, Wrench } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getTaskUsage } from '../api.js'
import { Card } from './ui.jsx'

const STAGES = {
  material_analysis: '素材分析', video_analysis: '参考片分析', agent_pipeline: '分镜规划',
  storyboard_render: '视频渲染', render: '视频渲染', asset_learning: '知识与示例沉淀',
  workflow_prepare: '分析与规划', workflow_render: '渲染与复审',
}
const number = (value) => value == null ? '未提供' : Number(value).toLocaleString('zh-CN')
function money(usage) {
  if (!usage?.costs?.length) return usage?.cost_status === 'not_used' ? '尚无模型调用' : '未计价'
  return usage.costs.map((cost) => `${Number(cost.amount) > 0 && Number(cost.amount) < .000001 ? '< ' : ''}${cost.currency === 'CNY' ? '¥' : '$'}${Number(cost.amount) > 0 && Number(cost.amount) < .000001 ? '0.000001' : Number(cost.amount).toFixed(6)}`).join(' + ')
}

export default function TaskUsage({ taskId, status, learningStatus, learningLoaded }) {
  const [usage, setUsage] = useState(null)
  const [error, setError] = useState('')
  const active = ['pending', 'running'].includes(status)
    || (status === 'success' && (!learningLoaded || ['pending', 'running', 'retrying'].includes(learningStatus)))
  useEffect(() => {
    const controller = new AbortController()
    let timer
    const refresh = async () => {
      try {
        const response = await getTaskUsage(taskId, { signal: controller.signal })
        if (!controller.signal.aborted) { setUsage(response.data); setError('') }
      } catch {
        if (!controller.signal.aborted) setError('执行用量暂时无法加载')
      } finally {
        if (active && !controller.signal.aborted) timer = setTimeout(refresh, 4000)
      }
    }
    refresh()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [taskId, active, status])
  const partial = usage?.source === 'legacy' || usage?.unreported_usage_calls > 0
  const reference = usage?.costs?.some((cost) => cost.basis?.includes('official_peak_reference'))
  const cards = [
    { label: 'Token 用量', icon: Hash, value: `${partial && usage?.tokens?.total_tokens != null ? '≥ ' : ''}${number(usage?.tokens?.total_tokens)}`, hint: `输入 ${number(usage?.tokens?.prompt_tokens)} / 输出 ${number(usage?.tokens?.completion_tokens)}` },
    { label: reference ? '参考费用上限' : '模型费用估算', icon: Coins, value: money(usage), hint: usage?.cost_status === 'partial' ? `已计价 ${usage.priced_calls} / ${usage.model_calls} 次请求` : '按调用时的单价快照计算' },
    { label: '工具调用', icon: Wrench, value: number(usage?.tool_calls), hint: usage?.failed_tool_calls ? `其中 ${usage.failed_tool_calls} 次执行失败` : '抽帧、音频、渲染及 Agent 工具' },
    { label: '模型请求', icon: Activity, value: number(usage?.model_calls), hint: usage?.source === 'events' ? `含 ${usage.retries} 次重试 · 失败 ${usage.failed_model_calls} 次` : '历史任务仅保留已有汇总' },
  ]
  return (
    <Card className="mb-6 p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-white">本次执行用量</h2>
        <span className="text-xs text-[#8888a8]">{active ? '执行中持续更新' : '包含已记录的分析、渲染与后处理'}</span>
      </div>
      {error && <p className="mb-3 text-xs text-amber-600">{error}</p>}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {cards.map(({ label, icon: Icon, value, hint }) => (
          <div key={label} className="rounded-xl border border-[#e4e4ed] bg-[#fafafe] p-3">
            <div className="flex items-center gap-1.5 text-xs text-[#777795]"><Icon size={14} />{label}</div>
            <p className="my-2 break-words text-xl font-semibold tabular-nums text-[#28283c]">{usage ? value : '加载中…'}</p>
            <p className="text-[11px] leading-5 text-[#777795]">{hint}</p>
          </div>
        ))}
      </div>
      {usage && <p className="mt-3 text-xs leading-5 text-[#777795]">{usage.notice}</p>}
      {usage?.unreported_usage_calls > 0 && <p className="mt-1 text-xs text-amber-700">有 {usage.unreported_usage_calls} 次请求未返回完整 Token 用量，汇总可能不完整。</p>}
      {usage?.mock_calls > 0 && <p className="mt-1 text-xs text-amber-700">另有 {usage.mock_calls} 次模拟响应，不计入实际模型请求。</p>}
      {reference && <p className="mt-1 text-xs text-[#777795]">部分模型使用 DeepSeek 官方峰时参考价（2026-10-26），实际低峰价格及账户折扣可能更低。</p>}
      <p className="mt-1 text-xs text-[#777795]">可在 <Link to="/settings" className="text-indigo-600 underline underline-offset-2">模型与 API</Link> 配置单价；不同币种分别显示，不做自动汇率换算。以服务商账单为准。</p>
      {usage?.stages?.length > 0 && (
        <details className="mt-4 border-t border-[#e4e4ed] pt-3">
          <summary className="cursor-pointer text-xs font-medium text-[#777795]">展开阶段与工具明细</summary>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[#8888a8]"><tr><th className="pb-2 pr-3">阶段</th><th className="pb-2 pr-3">Token</th><th className="pb-2 pr-3">模型请求</th><th className="pb-2 pr-3">工具调用</th><th className="pb-2">费用估算</th></tr></thead>
              <tbody>{usage.stages.map((row) => <tr key={row.stage} className="border-t border-[#ededf4]"><td className="py-2 pr-3">{STAGES[row.stage] || row.stage}</td><td className="pr-3 tabular-nums">{number(row.tokens?.total_tokens)}</td><td className="pr-3">{row.model_calls}</td><td className="pr-3">{row.tool_calls}</td><td className="whitespace-nowrap">{money(row)}{row.cost_status === 'partial' ? '（部分）' : ''}</td></tr>)}</tbody>
            </table>
          </div>
          {usage.models.length > 0 && <p className="mt-3 text-xs text-[#777795]">模型：{usage.models.map((row) => `${row.model}（${row.model_calls} 次，${number(row.tokens.total_tokens)} Token）`).join('；')}</p>}
          <div className="mt-3 flex flex-wrap gap-2">{usage.tools.map((tool) => <span key={tool.name} className="rounded-md bg-[#f0f0f8] px-2 py-1 text-[11px] text-[#666681]">{tool.name} × {tool.calls}</span>)}</div>
        </details>
      )}
    </Card>
  )
}
