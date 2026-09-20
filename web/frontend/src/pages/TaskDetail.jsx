import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Bot, Download, Trash2 } from 'lucide-react'
import { deleteTask, downloadTaskResult, getStoryboard, getTask, getTaskEvaluation, mediaUrl } from '../api.js'
import {
  Button,
  Card,
  InfoBar,
  ProgressBar,
  SectionHeader,
  StatusPill,
} from '../components/ui.jsx'
import StepTimeline from '../components/StepTimeline.jsx'
import LogTerminal from '../components/LogTerminal.jsx'
import StoryboardEditor from '../components/StoryboardEditor.jsx'

const TASK_TYPE_LABELS = {
  end_to_end: '端到端生成',
  material_analysis: '素材分析',
  analyze_video: '视频结构分析',
}

const EVALUATION_CHECK_LABELS = {
  pipeline_summary: '运行摘要',
  run_info: '运行信息',
  agent_stage_coverage: 'Agent 阶段',
  structured_artifacts: '方案与素材',
  pipeline_errors: '执行错误',
  review_artifact: '评审记录',
  review_pass: '方案评审',
  media_output: '视频解码',
  video_duration: '视频时长',
  material_coverage: '素材覆盖',
  model_execution: '模型调用',
  render_review_artifact: '成片评审记录',
  render_review_current: '成片评审版本',
}

function WsDot({ status }) {
  const meta = {
    connected:    { color: 'bg-[#34d399]', label: '实时连接已建立' },
    connecting:   { color: 'bg-[#fbbf24] vc-pulse-dot', label: '连接中...' },
    disconnected: { color: 'bg-[#5a5a7a]', label: '连接已断开' },
    error:       { color: 'bg-[#f87171]', label: '连接异常' },
  }[status] || { color: 'bg-[#5a5a7a]', label: status }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-[#8888a8]">
      <span className={`h-1.5 w-1.5 rounded-full ${meta.color}`} />
      {meta.label}
    </span>
  )
}

export default function TaskDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [task, setTask] = useState(null)
  const [logs, setLogs] = useState([])
  const [draft, setDraft] = useState(null)
  const [draftError, setDraftError] = useState('')
  const [evaluation, setEvaluation] = useState(null)
  const [wsStatus, setWsStatus] = useState('connecting')
  const wsRef = useRef(null)

  const fetchTask = useCallback(async () => {
    try {
      const res = await getTask(id)
      setTask(res.data)
      setLogs(res.data.logs || [])
    } catch {
      navigate('/')
    }
  }, [id, navigate])

  useEffect(() => {
    fetchTask()

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/api/tasks/${id}/ws`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => setWsStatus('connected')
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      if (msg.type === 'progress') {
        setLogs((prev) => [...prev, msg.data])
      } else if (msg.type === 'status') {
        fetchTask()
      }
    }
    ws.onclose = () => setWsStatus('disconnected')
    ws.onerror = () => setWsStatus('error')

    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping')
    }, 30000)

    return () => {
      clearInterval(ping)
      ws.close()
    }
  }, [fetchTask, id])

  useEffect(() => {
    if (task?.status !== 'awaiting_confirmation') {
      setDraft(null)
      setDraftError('')
      return
    }
    getStoryboard(id)
      .then((response) => {
        setDraft(response.data)
        setDraftError('')
      })
      .catch((error) => setDraftError(error.response?.data?.detail || '分镜草案加载失败'))
  }, [id, task?.status, task?.draft_revision])

  useEffect(() => {
    if (!['awaiting_confirmation', 'success', 'failed'].includes(task?.status)) {
      setEvaluation(null)
      return
    }
    if (task.status === 'awaiting_confirmation' && task.draft_revision > 0) {
      setEvaluation(null)
      return
    }
    getTaskEvaluation(id)
      .then((response) => setEvaluation(response.data))
      .catch(() => setEvaluation(null))
  }, [id, task?.status, task?.draft_revision])

  const handleDownload = async () => {
    try {
      const res = await downloadTaskResult(id)
      const isVideo = task.type === 'end_to_end'
      const blob = new Blob([res.data], {
        type: isVideo ? 'video/mp4' : 'application/json',
      })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = isVideo ? `task_${id}_result.mp4` : `task_${id}_result.json`
      a.click()
      window.URL.revokeObjectURL(url)
    } catch {
      alert('下载失败')
    }
  }

  const handleDelete = async () => {
    if (!confirm('确定删除该任务？')) return
    await deleteTask(id)
    navigate(task.project_id ? `/projects/${task.project_id}` : '/')
  }

  if (!task) {
    return <div className="py-16 text-center text-sm text-[#5a5a7a]">加载中...</div>
  }

  const isSuccess = task.status === 'success' && task.result_path
  const typeLabel = TASK_TYPE_LABELS[task.type] || task.type

  return (
    <div>
      <SectionHeader
        title={`任务 #${task.id}`}
        description={typeLabel}
        backTo={task.project_id ? `/projects/${task.project_id}` : '/'}
        actions={
          <>
            <Button
              variant="secondary"
              icon={Bot}
              onClick={() => navigate(`/assistant?project_id=${task.project_id}&task_id=${task.id}`)}
            >
              智能助手
            </Button>
            {isSuccess && (
              <Button icon={Download} onClick={handleDownload}>
                {task.type === 'end_to_end' ? '下载视频' : '下载结果'}
              </Button>
            )}
            <Button variant="danger" icon={Trash2} onClick={handleDelete}>
              删除
            </Button>
          </>
        }
      />

      {/* 状态概览卡 */}
      <Card className="mb-6 p-5">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <StatusPill status={task.status} />
            <span className="text-sm text-[#8888a8]">进度 {task.progress}%</span>
          </div>
          <WsDot status={wsStatus} />
        </div>

        <StepTimeline logs={logs} taskStatus={task.status} taskType={task.type} />

        <ProgressBar value={task.progress} className="mt-5" />
      </Card>

      {/* 错误信息 */}
      {task.error_message && (
        <div className="mb-6">
          <InfoBar type="error">{task.error_message}</InfoBar>
        </div>
      )}

      {task.status === 'awaiting_confirmation' && draftError && (
        <div className="mb-6">
          <InfoBar type="error">{draftError}</InfoBar>
        </div>
      )}

      {task.status === 'awaiting_confirmation' && draft && (
        <StoryboardEditor
          taskId={task.id}
          draft={draft}
          onDraftChange={(nextDraft) => {
            setDraft(nextDraft)
            setTask((current) => ({ ...current, draft_revision: nextDraft.revision }))
          }}
          onConfirmed={(nextTask) => {
            setTask(nextTask)
            setLogs(nextTask.logs || [])
            setDraft(null)
          }}
        />
      )}

      {/* 视频预览（仅端到端任务） */}
      {isSuccess && task.type === 'end_to_end' && (
        <Card className="mb-6 p-5">
          <h2 className="mb-3 text-sm font-semibold text-white">生成结果</h2>
          <video
            src={mediaUrl(`/tasks/${id}/download`)}
            controls
            className="w-full rounded-xl bg-black"
          />
        </Card>
      )}

      {evaluation && (
        <Card className="mb-6 p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-white">Agent 评测</h2>
            <span className="text-sm text-[#8888a8]">
              {evaluation.phase === 'awaiting_confirmation' ? '草案阶段' : '最终结果'} · {evaluation.score} 分
            </span>
          </div>
          <p className="text-sm text-[#b8b8ce]">
            {evaluation.phase === 'awaiting_confirmation'
              ? (evaluation.ready_for_render ? '草案生成与阶段记录完整，等待确认渲染。' : '草案阶段存在待检查项。')
              : (evaluation.success ? '方案评审与视频技术检查通过。' : '评测发现待检查项，视频仍可单独查看。')}
          </p>
          {evaluation.phase !== 'awaiting_confirmation' && (
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-[#8888a8]">
              <span>Reviewer：{evaluation.quality?.review_score ?? '未完成'}</span>
              <span>成片视觉评审：{evaluation.quality?.render_review_score ?? (evaluation.quality?.render_review_status === 'skipped' ? '未配置' : '未完成')}</span>
              <span>全片解码：{evaluation.media?.full_decode_valid ? '通过' : '未通过'}</span>
              <span>音轨：{evaluation.media?.has_audio === false ? '未检测到' : evaluation.media?.has_audio === true ? '存在' : '未知'}</span>
              <span>素材覆盖：{evaluation.quality?.material_coverage == null ? '未知' : `${Math.round(evaluation.quality.material_coverage * 100)}%`}</span>
              <span>模型 Token：{evaluation.llm_usage?.total_tokens ?? '未提供'}</span>
            </div>
          )}
          {evaluation.render_review && (
            <div className="mt-3 rounded-lg border border-[#2d2d4a] bg-[#151524] p-3 text-xs">
              <p className="text-[#d9d9ec]">
                成片评测：{evaluation.render_review.status === 'completed' ? (evaluation.render_review.summary || '已基于分镜时间轴抽帧完成视觉评审。') : (evaluation.render_review.reason || '仅保留技术检查与抽帧证据。')}
              </p>
              {evaluation.render_review.technical?.issues?.length > 0 && (
                <ul className="mt-2 space-y-1 text-[#fbbf24]">
                  {evaluation.render_review.technical.issues.slice(0, 3).map((issue, index) => (
                    <li key={`${issue.type}-${index}`}>{issue.detail}{issue.start != null ? `（${issue.start}s–${issue.end}s）` : ''}</li>
                  ))}
                </ul>
              )}
              {evaluation.render_review.issues?.length > 0 && (
                <ul className="mt-2 space-y-1 text-[#fbbf24]">
                  {evaluation.render_review.issues.slice(0, 3).map((issue, index) => (
                    <li key={`${issue.category}-${index}`}>{issue.description}{issue.evidence_times?.length ? `（${issue.evidence_times.join(', ')}s）` : ''}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {evaluation.checks?.some((check) => !check.passed) && (
            <ul className="mt-3 space-y-1 text-xs text-[#fbbf24]">
              {evaluation.checks.filter((check) => !check.passed).map((check) => (
                <li key={check.name}>{EVALUATION_CHECK_LABELS[check.name] || check.name}：{check.detail}</li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {/* 日志终端 */}
      <LogTerminal logs={logs} />
    </div>
  )
}
