import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ChevronRight,
  Bot,
  FileAudio,
  Film,
  Image as ImageIcon,
  Images,
  Loader2,
  Sparkles,
  Trash2,
} from 'lucide-react'
import {
  createTask,
  deleteMaterial,
  getProject,
  listMaterials,
  listTasks,
  mediaUrl,
  uploadMaterial,
} from '../api.js'
import {
  Badge,
  Button,
  Card,
  Field,
  SectionHeader,
  SelectInput,
  StatusPill,
} from '../components/ui.jsx'

const MODE_META = {
  editing_transfer: { label: '编辑迁移', color: 'purple' },
  agent_pipeline: { label: '多智能体', color: 'blue' },
}

const TASK_TYPE_OPTIONS = [
  {
    value: 'end_to_end',
    label: '完整生成：分析 → 分镜确认 → 渲染',
    hint: '先生成可编辑分镜，确认后再产出成片',
  },
  { value: 'material_analysis', label: '仅素材分析', hint: '只分析照片素材，用于调试' },
  { value: 'analyze_video', label: '仅视频结构分析', hint: '只分析参考视频结构，用于调试' },
]

function MaterialTypeIcon({ type }) {
  if (type === 'video') return <Film size={16} className="text-[#b49aff]" />
  if (type === 'image') return <ImageIcon size={16} className="text-[#6ee7b7]" />
  return <FileAudio size={16} className="text-[#fcd34d]" />
}

function UploadZone({ icon: Icon, label, hint, accept, uploading, onChange }) {
  return (
    <label
      className={`flex flex-1 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-6 text-center transition-all duration-200 ${
        uploading
          ? 'border-[#2a2a42] bg-[rgba(124,92,252,0.04)]'
          : 'border-[#2a2a42] hover:border-[#7c5cfc] hover:bg-[rgba(124,92,252,0.06)]'
      }`}
    >
      {uploading ? (
        <Loader2 size={22} className="animate-spin text-[#7c5cfc]" />
      ) : (
        <Icon size={22} className="text-[#5a5a7a]" />
      )}
      <span className="mt-2 text-sm font-medium text-[#c8c8e0]">
        {uploading ? '上传中...' : label}
      </span>
      <span className="mt-0.5 text-xs text-[#5a5a7a]">{hint}</span>
      <input
        type="file"
        accept={accept}
        className="hidden"
        onChange={onChange}
        disabled={uploading}
      />
    </label>
  )
}

export default function ProjectDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [materials, setMaterials] = useState([])
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [taskType, setTaskType] = useState('end_to_end')
  const [previewId, setPreviewId] = useState(null)

  const fetchAll = useCallback(async () => {
    try {
      const [pRes, mRes, tRes] = await Promise.all([
        getProject(id),
        listMaterials(id),
        listTasks(id),
      ])
      setProject(pRes.data)
      setMaterials(mRes.data)
      setTasks(tRes.data)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  const handleUpload = async (e, type, role) => {
    const file = e.target.files[0]
    e.target.value = ''
    if (!file) return
    setUploading(true)
    try {
      const resolvedType = type || (file.type.startsWith('video/') ? 'video' : 'image')
      await uploadMaterial(id, file, resolvedType, role)
      fetchAll()
    } catch (err) {
      alert(err.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteMaterial = async (matId) => {
    if (!confirm('确定删除该素材？')) return
    await deleteMaterial(matId)
    fetchAll()
  }

  const handleCreateTask = async () => {
    const videos = materials.filter((m) => m.type === 'video')
    const reference = videos.find((m) => m.meta?.role === 'reference') || videos[0]
    const hasTarget = materials.some((m) => (
      m.id !== reference?.id
      && ['image', 'video'].includes(m.type)
      && m.meta?.role !== 'reference'
    ))
    if (taskType === 'analyze_video' && !reference) {
      alert('视频结构分析需要至少一个参考视频')
      return
    }
    if (taskType === 'material_analysis' && !hasTarget) {
      alert('素材分析需要至少一张照片或一段视频')
      return
    }
    if (taskType === 'end_to_end' && (!reference || !hasTarget)) {
      alert('完整生成需要一个参考视频和至少一个图片/视频素材')
      return
    }
    setCreating(true)
    try {
      const res = await createTask(id, taskType)
      navigate(`/tasks/${res.data.id}`)
    } catch (err) {
      alert(err.response?.data?.detail || '创建任务失败')
    } finally {
      setCreating(false)
    }
  }

  if (loading) {
    return <div className="py-16 text-center text-sm text-[#5a5a7a]">加载中...</div>
  }
  if (!project) {
    return <div className="py-16 text-center text-sm text-[#5a5a7a]">项目不存在</div>
  }

  const modeMeta = MODE_META[project.pipeline_mode] || MODE_META.editing_transfer
  const currentTypeOption = TASK_TYPE_OPTIONS.find((o) => o.value === taskType)
  const projectVideos = materials.filter((m) => m.type === 'video')
  const referenceMaterial = projectVideos.find((m) => m.meta?.role === 'reference') || projectVideos[0]
  const previewMaterial = materials.find((material) => material.id === previewId) || referenceMaterial || materials[0]
  const targetCount = materials.filter((material) => material.id !== referenceMaterial?.id && material.meta?.role !== 'reference').length

  return (
    <div>
      <SectionHeader
        title={project.name}
        description={project.topic || '未设置主题'}
        backTo="/projects"
        actions={(
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              icon={Bot}
              onClick={() => navigate(`/assistant?project_id=${id}`)}
            >
              智能助手
            </Button>
            <Badge color={modeMeta.color}>{modeMeta.label}</Badge>
          </div>
        )}
      />

      <div className="vc-project-workspace">
        {/* 素材管理 */}
        <Card className="vc-project-materials p-5">
          <div className="vc-panel-heading"><div><span>MEDIA WORKSPACE</span><h2>素材工作区</h2></div><Badge color="indigo">{materials.length} 个素材</Badge></div>

          <div className="mb-5 grid gap-3 sm:grid-cols-2">
            <UploadZone
              icon={Film}
              label="上传参考视频"
              hint="爆款视频，用于提取结构"
              accept="video/*"
              uploading={uploading}
              onChange={(e) => handleUpload(e, 'video', 'reference')}
            />
            <UploadZone
              icon={Images}
              label="上传照片/视频"
              hint="你的实拍素材，可多次上传"
              accept="image/*,video/*"
              uploading={uploading}
              onChange={(e) => handleUpload(e, null, 'target')}
            />
          </div>

          {previewMaterial && (
            <div className="vc-material-preview mb-5">
              <div className="vc-material-preview-head">
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-[#654cc2]">{previewMaterial.id === referenceMaterial?.id ? '参考视频' : '素材预览'}</p>
                  <p className="mt-0.5 truncate text-xs text-[#8b8495]">{previewMaterial.filename}</p>
                </div>
                <Badge color={previewMaterial.id === referenceMaterial?.id ? 'indigo' : 'blue'}>{previewMaterial.id === referenceMaterial?.id ? '结构与节奏来源' : '创作素材'}</Badge>
              </div>
              <div className="vc-material-preview-stage">
              {previewMaterial.type === 'video' ? (
              <video
                key={previewMaterial.id}
                src={mediaUrl(`/materials/${previewMaterial.id}/media`)}
                controls
                preload="metadata"
                playsInline
              >
                当前浏览器不支持视频播放。
              </video>
              ) : previewMaterial.type === 'image' ? (
                <img src={mediaUrl(`/materials/${previewMaterial.id}/media`)} alt={previewMaterial.filename} />
              ) : (
                <audio key={previewMaterial.id} src={mediaUrl(`/materials/${previewMaterial.id}/media`)} controls preload="metadata" />
              )}
              </div>
            </div>
          )}

          {materials.length === 0 ? (
            <p className="py-6 text-center text-sm text-[#5a5a7a]">
              还没有素材，先上传一个参考视频和几张照片吧
            </p>
          ) : (
            <ul className="vc-material-grid" aria-label="项目素材">
              {materials.map((m) => (
                <li key={m.id} className={`vc-material-item ${previewMaterial?.id === m.id ? 'is-selected' : ''}`}>
                  <button type="button" className="vc-material-select" aria-pressed={previewMaterial?.id === m.id} onClick={() => setPreviewId(m.id)} title={`预览 ${m.filename}`}>
                    <span className="vc-material-type"><MaterialTypeIcon type={m.type} /></span>
                    <span>{m.filename}</span>
                  </button>
                  <div className="vc-material-item-footer">
                    <Badge color={m.type === 'video' ? 'indigo' : 'green'}>
                      {m.id === referenceMaterial?.id || m.meta?.role === 'reference'
                        ? '参考视频'
                        : m.type === 'video' ? '视频素材' : m.type === 'image' ? '图片素材' : '音频'}
                    </Badge>
                    <button
                      onClick={() => handleDeleteMaterial(m.id)}
                      title="删除素材"
                      aria-label={`删除素材 ${m.filename}`}
                      className="rounded-lg p-1 text-[#5a5a7a] transition-all hover:bg-[rgba(248,113,113,0.08)] hover:text-[#f87171]"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* 生成任务 */}
        <Card className="vc-project-run-panel p-5">
          <div className="vc-panel-heading"><div><span>GENERATION</span><h2>生成任务</h2></div></div>
          <div className="vc-project-readiness">
            <span className={referenceMaterial ? 'is-ready' : ''}><i />{referenceMaterial ? '参考视频已就绪' : '等待添加参考视频'}</span>
            <span className={targetCount ? 'is-ready' : ''}><i />{targetCount ? `${targetCount} 个创作素材` : '等待添加创作素材'}</span>
          </div>

          <Field label="执行步骤" hint={currentTypeOption?.hint} className="mb-4">
            <SelectInput value={taskType} onChange={(e) => setTaskType(e.target.value)}>
              {TASK_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </SelectInput>
          </Field>

          <Button
            onClick={handleCreateTask}
            loading={creating}
            icon={Sparkles}
            size="lg"
            className="w-full"
          >
            {taskType === 'end_to_end' ? '生成分镜草案' : '运行该步骤'}
          </Button>

          <h3 className="mb-2 mt-6 text-[11px] font-semibold uppercase tracking-wider text-[#5a5a7a]">
            历史任务
          </h3>
          {tasks.length === 0 ? (
            <p className="py-4 text-center text-sm text-[#5a5a7a]">还没有运行过任务</p>
          ) : (
            <ul className="-mx-2 divide-y divide-[#2a2a42] overflow-y-auto">
              {tasks.map((t) => (
                <li key={t.id}>
                  <button
                    onClick={() => navigate(`/tasks/${t.id}`)}
                    className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2.5 text-left transition-colors hover:bg-[rgba(255,255,255,0.03)]"
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span className="text-sm font-medium text-[#c8c8e0]">#{t.id}</span>
                      <StatusPill status={t.status} />
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5 text-xs text-[#5a5a7a]">
                      {t.progress}%
                      <ChevronRight size={14} />
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
