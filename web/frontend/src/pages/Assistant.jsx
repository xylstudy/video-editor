import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, ExternalLink, FileVideo, Loader2, MessageSquare, Paperclip, Plus, Send, Sparkles, X } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import {
  createChatSession,
  clearChatContext,
  listChatMessages,
  listChatSessions,
  sendChatMessage,
  updateChatContext,
  uploadChatAttachment,
} from '../api.js'
import { Button, Card, InfoBar, SectionHeader } from '../components/ui.jsx'

const SUGGESTIONS = [
  '有哪些项目？',
  '查看最近任务进度',
  '分析当前项目的参考视频',
  '生成一个分镜方案',
  '查看统计洞察',
]

function contextFromPath(pathname, search = '') {
  const context = { route: pathname }
  const project = pathname.match(/\/projects\/(\d+)/)
  const task = pathname.match(/\/tasks\/(\d+)/)
  const gene = pathname.match(/\/genes\/(\d+)/)
  if (project) context.project_id = Number(project[1])
  if (task) context.task_id = Number(task[1])
  if (gene) context.gene_id = Number(gene[1])
  const params = new URLSearchParams(search)
  for (const key of ['project_id', 'task_id', 'gene_id']) {
    const value = Number(params.get(key))
    if (value > 0 && !context[key]) context[key] = value
  }
  return context
}

function hasWorkspaceTarget(context) {
  return ['project_id', 'task_id', 'gene_id'].some((key) => Number(context[key]) > 0)
}

function messageTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function ActionCard({ metadata }) {
  if (!metadata || (!metadata.route && !metadata.task_id && !metadata.project_id)) return null
  const route = metadata.route
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-[rgba(124,92,252,0.2)] bg-[rgba(124,92,252,0.07)] p-3 text-xs text-[#bdb0ef]">
      <Sparkles size={14} className="shrink-0 text-[#b49aff]" />
      {metadata.task_id && <span>任务 #{metadata.task_id}{metadata.status ? ` · ${metadata.status}` : ''}</span>}
      {route && (
        <Link
          to={route}
          className="ml-auto inline-flex items-center gap-1 font-medium text-[#66e0ff] hover:text-[#00d4ff]"
        >
          打开相关页面
          <ExternalLink size={13} />
        </Link>
      )}
    </div>
  )
}

function ChatBubble({ message }) {
  const isUser = message.role === 'user'
  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[rgba(124,92,252,0.14)] text-[#b49aff]">
          <Bot size={16} />
        </div>
      )}
      <div className={`max-w-[min(720px,85%)] ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-6 whitespace-pre-wrap ${
            isUser
              ? 'rounded-br-md bg-[#7c5cfc] text-white'
              : 'rounded-bl-md border border-[#2a2a42] bg-[#1a1a29] text-[#d8d8e8]'
          }`}
        >
          {message.content}
        </div>
        {!isUser && <ActionCard metadata={message.metadata} />}
        <div className={`mt-1 text-[10px] text-[#555572] ${isUser ? 'text-right' : ''}`}>
          {messageTime(message.created_at)}
        </div>
      </div>
      {isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[rgba(0,212,255,0.12)] text-[10px] font-bold text-[#66e0ff]">
          我
        </div>
      )}
    </div>
  )
}

function ThinkingBubble() {
  return (
    <div className="flex gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[rgba(124,92,252,0.14)] text-[#b49aff]">
        <Bot size={16} />
      </div>
      <div className="rounded-2xl rounded-bl-md border border-[#2a2a42] bg-[#1a1a29] px-4 py-3">
        <div className="flex items-center gap-1.5" aria-label="助手正在思考">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#8b73ea]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#8b73ea] [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#8b73ea] [animation-delay:300ms]" />
          <span className="ml-1 text-xs text-[#8888a8]">正在思考…</span>
        </div>
      </div>
    </div>
  )
}

function WorkspaceContext({ context, onClear, disabled }) {
  const entries = [
    context?.project_id && { key: 'project', label: `项目 #${context.project_id}` },
    context?.task_id && { key: 'task', label: `任务 #${context.task_id}` },
    context?.gene_id && { key: 'gene', label: `视频基因 #${context.gene_id}` },
  ].filter(Boolean)

  if (!entries.length) {
    return (
      <div className="mb-4 rounded-xl border border-dashed border-[#2a2a42] bg-[#14141f] px-3 py-2 text-xs text-[#6f6f8e]">
        当前未锁定项目或任务；涉及执行的指令会要求你明确选择对象。
      </div>
    )
  }

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-[rgba(0,212,255,0.16)] bg-[rgba(0,212,255,0.05)] px-3 py-2">
      <span className="text-[11px] font-medium text-[#77dced]">当前工作上下文</span>
      {entries.map((entry) => (
        <span key={entry.key} className="rounded-md bg-[rgba(0,212,255,0.1)] px-2 py-1 text-[11px] text-[#b8f4ff]">
          {entry.label}
        </span>
      ))}
      <button
        type="button"
        onClick={onClear}
        disabled={disabled}
        className="ml-auto text-[11px] text-[#8e8ea9] transition hover:text-[#ff9b9b] disabled:cursor-not-allowed disabled:opacity-50"
      >
        清除上下文
      </button>
    </div>
  )
}

function WorkflowMemory({ memory }) {
  const goal = memory?.current_goal
  const nextStep = memory?.next_step
  const decisions = Array.isArray(memory?.decisions) ? memory.decisions.slice(-2) : []
  const constraints = Array.isArray(memory?.constraints) ? memory.constraints.slice(-2) : []
  if (!goal && !nextStep && !decisions.length && !constraints.length) return null

  return (
    <div className="mb-4 rounded-xl border border-[rgba(124,92,252,0.18)] bg-[rgba(124,92,252,0.05)] px-3 py-2.5 text-xs">
      <div className="mb-1.5 font-medium text-[#bdaeff]">工作记忆</div>
      {goal && <p className="text-[#c9c7db]">目标：{goal}</p>}
      {nextStep && <p className="mt-1 text-[#8e8ea9]">下一步：{nextStep}</p>}
      {(decisions.length > 0 || constraints.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {decisions.map((item) => (
            <span key={`decision-${item}`} className="rounded-md bg-[rgba(124,92,252,0.12)] px-2 py-1 text-[11px] text-[#c9baff]">决策：{item}</span>
          ))}
          {constraints.map((item) => (
            <span key={`constraint-${item}`} className="rounded-md bg-[rgba(255,159,159,0.1)] px-2 py-1 text-[11px] text-[#ffb3b3]">约束：{item}</span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Assistant() {
  const location = useLocation()
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [paging, setPaging] = useState({ hasMore: false, nextBeforeId: null, loadingOlder: false })
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [attachments, setAttachments] = useState([])
  const [uploadingAttachment, setUploadingAttachment] = useState(false)
  const [error, setError] = useState('')
  const messageEndRef = useRef(null)
  const fileInputRef = useRef(null)
  const initializedRef = useRef(false)
  const workspaceSyncRef = useRef('')
  const shouldScrollToEndRef = useRef(true)

  const loadMessages = useCallback(async (sessionId) => {
    setActiveSessionId(sessionId)
    setMessages([])
    setPaging({ hasMore: false, nextBeforeId: null, loadingOlder: false })
    setAttachments([])
    try {
      const response = await listChatMessages(sessionId, { limit: 50 })
      const payload = response.data
      const items = Array.isArray(payload) ? payload : (payload.items || [])
      setMessages(items)
      setPaging({
        hasMore: Boolean(payload?.has_more),
        nextBeforeId: payload?.next_before_id || null,
        loadingOlder: false,
      })
    } catch (requestError) {
      setError(requestError.response?.data?.detail || '对话记录加载失败')
    }
  }, [])

  const initialize = useCallback(async () => {
    if (initializedRef.current) return
    initializedRef.current = true
    setLoading(true)
    setError('')
    try {
      const response = await listChatSessions()
      const available = response.data || []
      if (available.length) {
        setSessions(available)
        await loadMessages(available[0].id)
      } else {
        const created = await createChatSession({ title: '新对话', context: contextFromPath(location.pathname, location.search) })
        setSessions([created.data])
        setActiveSessionId(created.data.id)
        setMessages([])
      }
    } catch (requestError) {
      setError(requestError.response?.data?.detail || '智能助手暂时无法连接，请确认后端已启动')
    } finally {
      setLoading(false)
    }
  }, [loadMessages, location.pathname, location.search])

  useEffect(() => {
    initialize()
  }, [initialize])

  useEffect(() => {
    const pageContext = contextFromPath(location.pathname, location.search)
    if (!activeSessionId || !hasWorkspaceTarget(pageContext)) return
    const signature = `${location.pathname}?${location.search}`
    if (workspaceSyncRef.current === signature) return
    workspaceSyncRef.current = signature
    let cancelled = false
    updateChatContext(activeSessionId, pageContext)
      .then((response) => {
        if (cancelled) return
        setSessions((current) => current.map((item) => (
          item.id === activeSessionId ? response.data : item
        )))
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(requestError.response?.data?.detail || '当前工作上下文同步失败')
        }
      })
    return () => { cancelled = true }
  }, [activeSessionId, location.pathname, location.search])

  useEffect(() => {
    if (shouldScrollToEndRef.current) {
      messageEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
    shouldScrollToEndRef.current = true
  }, [messages, sending])

  const handleNewSession = async () => {
    setError('')
    try {
      const response = await createChatSession({ title: '新对话', context: contextFromPath(location.pathname, location.search) })
      setSessions((current) => [response.data, ...current])
      setActiveSessionId(response.data.id)
      setMessages([])
      setPaging({ hasMore: false, nextBeforeId: null, loadingOlder: false })
      setAttachments([])
    } catch (requestError) {
      setError(requestError.response?.data?.detail || '新建对话失败')
    }
  }

  const handleLoadOlderMessages = async () => {
    if (!activeSessionId || !paging.hasMore || !paging.nextBeforeId || paging.loadingOlder) return
    shouldScrollToEndRef.current = false
    setPaging((current) => ({ ...current, loadingOlder: true }))
    try {
      const response = await listChatMessages(activeSessionId, {
        limit: 50,
        before_id: paging.nextBeforeId,
      })
      const payload = response.data
      const items = Array.isArray(payload) ? payload : (payload.items || [])
      setMessages((current) => [...items, ...current])
      setPaging({
        hasMore: Boolean(payload?.has_more),
        nextBeforeId: payload?.next_before_id || null,
        loadingOlder: false,
      })
    } catch (requestError) {
      setError(requestError.response?.data?.detail || '更早的对话记录加载失败')
      shouldScrollToEndRef.current = true
      setPaging((current) => ({ ...current, loadingOlder: false }))
    }
  }

  const handleClearWorkspace = async () => {
    if (!activeSessionId || sending) return
    setError('')
    try {
      const response = await clearChatContext(activeSessionId)
      setSessions((current) => current.map((item) => (
        item.id === activeSessionId ? response.data : item
      )))
      workspaceSyncRef.current = `${location.pathname}?${location.search}`
    } catch (requestError) {
      setError(requestError.response?.data?.detail || '工作上下文清除失败')
    }
  }

  const handleAttachmentChange = async (event) => {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    if (!files.length || !activeSessionId) return
    setUploadingAttachment(true)
    setError('')
    try {
      const uploaded = []
      for (const file of files) {
        const response = await uploadChatAttachment(activeSessionId, file)
        uploaded.push(response.data)
      }
      setAttachments((current) => [...current, ...uploaded])
    } catch (requestError) {
      setError(requestError.response?.data?.detail || '附件上传失败，请检查文件格式和大小')
    } finally {
      setUploadingAttachment(false)
    }
  }

  const handleSend = async (event) => {
    event?.preventDefault()
    const content = draft.trim()
    if (!content || sending || !activeSessionId) return
    const optimisticId = `local-${Date.now()}`
    const sessionId = activeSessionId
    const optimisticMessage = {
      id: optimisticId,
      session_id: sessionId,
      role: 'user',
      content,
      message_type: 'text',
      metadata: {},
      created_at: new Date().toISOString(),
    }
    setDraft('')
    setSending(true)
    setError('')
    setMessages((current) => [...current, optimisticMessage])
    try {
      const response = await sendChatMessage(
        sessionId,
        content,
        {
          ...contextFromPath(location.pathname, location.search),
          attachment_ids: attachments.map((item) => item.id),
        },
      )
      setMessages((current) => [
        ...current.map((message) => (
          message.id === optimisticId ? response.data.user_message : message
        )),
        response.data.assistant_message,
      ])
      setSessions((current) => current.map((item) => (
        item.id === sessionId
          ? {
              ...item,
              title: item.title === '新对话' ? content.slice(0, 36) : item.title,
              context: response.data.context || item.context,
              memory: response.data.memory || item.memory,
              updated_at: new Date().toISOString(),
            }
          : item
      )))
      setAttachments([])
    } catch (requestError) {
      setError(requestError.response?.data?.detail || '消息发送失败，请稍后重试')
      setMessages((current) => current.filter((message) => message.id !== optimisticId))
      setDraft(content)
    } finally {
      setSending(false)
    }
  }

  const activeSession = sessions.find((item) => item.id === activeSessionId)

  return (
    <div>
      <SectionHeader
        title="智能助手"
        description="用自然语言控制视频分析、方案生成和任务流程"
        actions={(
          <Button variant="secondary" icon={Plus} onClick={handleNewSession}>
            新建对话
          </Button>
        )}
      />

      {error && <div className="mb-5"><InfoBar type="error">{error}</InfoBar></div>}

      <div className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
        <Card className="h-fit p-3">
          <div className="mb-2 flex items-center gap-2 px-2 py-2 text-xs font-semibold text-[#8888a8]">
            <MessageSquare size={14} /> 对话记录
          </div>
          <div className="space-y-1">
            {sessions.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => loadMessages(item.id)}
                disabled={sending}
                className={`w-full truncate rounded-lg px-3 py-2 text-left text-xs transition-colors ${
                  item.id === activeSessionId
                    ? 'bg-[rgba(124,92,252,0.14)] text-[#b49aff]'
                    : 'text-[#777795] hover:bg-[#1c1c2b] hover:text-[#d8d8e8]'
                } disabled:cursor-not-allowed disabled:opacity-50`}
              >
                {item.title || '新对话'}
              </button>
            ))}
          </div>
        </Card>

        <Card className="flex min-h-[620px] flex-col p-4 sm:p-5">
          <div className="mb-4 flex items-center gap-3 border-b border-[#2a2a42] pb-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-[#7c5cfc] to-[#00d4ff] text-white">
              <Bot size={20} />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-[#e8e8f0]">Video Claw Assistant</h2>
              <p className="mt-0.5 text-xs text-[#777795]">可以查询数据，也可以启动实际的视频工作流</p>
            </div>
          </div>

          <WorkspaceContext
            context={activeSession?.context}
            onClear={handleClearWorkspace}
            disabled={sending || loading}
          />
          <WorkflowMemory memory={activeSession?.memory} />

          <div className="flex-1 space-y-5 overflow-y-auto pr-1">
            {loading ? (
              <div className="flex h-64 items-center justify-center text-sm text-[#777795]">
                <Loader2 size={16} className="mr-2 animate-spin" /> 正在准备对话…
              </div>
            ) : messages.length === 0 ? (
              <div className="flex h-full min-h-[360px] flex-col items-center justify-center text-center">
                <div className="mb-4 rounded-2xl bg-[rgba(124,92,252,0.1)] p-4 text-[#b49aff]"><Sparkles size={24} /></div>
                <h3 className="text-base font-semibold text-[#e8e8f0]">从一句话开始</h3>
                <p className="mt-2 max-w-md text-sm leading-6 text-[#777795]">例如让我查看项目、启动视频分析，或者生成一份分镜方案。</p>
                <div className="mt-5 flex max-w-xl flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => setDraft(suggestion)}
                      className="rounded-full border border-[#2a2a42] bg-[#1a1a29] px-3 py-1.5 text-xs text-[#9999b5] transition-colors hover:border-[#4a3f77] hover:text-[#c8baff]"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {paging.hasMore && (
                  <div className="flex justify-center">
                    <button
                      type="button"
                      onClick={handleLoadOlderMessages}
                      disabled={paging.loadingOlder || sending}
                      className="rounded-full border border-[#2a2a42] px-3 py-1.5 text-[11px] text-[#8e8ea9] transition hover:border-[#4a3f77] hover:text-[#c8baff] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {paging.loadingOlder ? '正在加载…' : '加载更早的消息'}
                    </button>
                  </div>
                )}
                {messages.map((message) => <ChatBubble key={message.id} message={message} />)}
              </>
            )}
            {sending && <ThinkingBubble />}
            <div ref={messageEndRef} />
          </div>

          <div className="mt-5 border-t border-[#2a2a42] pt-4">
            {messages.length > 0 && (
              <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
                {SUGGESTIONS.slice(0, 3).map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => setDraft(suggestion)}
                    className="shrink-0 rounded-full border border-[#2a2a42] px-3 py-1 text-[11px] text-[#777795] hover:border-[#4a3f77] hover:text-[#c8baff]"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            )}
            {attachments.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-2">
                {attachments.map((attachment) => (
                  <div
                    key={attachment.id}
                    className="inline-flex max-w-full items-center gap-2 rounded-lg border border-[rgba(0,212,255,0.22)] bg-[rgba(0,212,255,0.07)] px-2.5 py-1.5 text-xs text-[#9feeff]"
                  >
                    <FileVideo size={13} className="shrink-0" />
                    <span className="max-w-[240px] truncate">{attachment.filename}</span>
                    <button
                      type="button"
                      onClick={() => setAttachments((current) => current.filter((item) => item.id !== attachment.id))}
                      className="text-[#6e9daa] transition hover:text-white"
                      aria-label="移除附件"
                    >
                      <X size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="mb-2 flex items-center gap-2 text-[11px] text-[#62627e]">
              <span>可上传视频或图片，然后直接告诉我想做什么</span>
            </div>
            <form onSubmit={handleSend} className="flex items-end gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept="video/*,image/*,audio/*"
                multiple
                className="hidden"
                onChange={handleAttachmentChange}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploadingAttachment || sending || !activeSessionId}
                className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-[#2a2a42] bg-[#1c1c2b] text-[#8888a8] transition hover:border-[#4a3f77] hover:text-[#c8baff] disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="上传附件"
              >
                {uploadingAttachment ? <Loader2 size={17} className="animate-spin" /> : <Paperclip size={17} />}
              </button>
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    handleSend(event)
                  }
                }}
                rows={2}
                maxLength={4000}
                placeholder="告诉我你想完成什么…（Enter 发送，Shift+Enter 换行）"
                className="min-h-[48px] flex-1 resize-none rounded-xl border border-[#2a2a42] bg-[#1c1c2b] px-3 py-2.5 text-sm leading-6 text-[#e8e8f0] outline-none transition-colors placeholder:text-[#5a5a7a] focus:border-[#7c5cfc] focus:ring-1 focus:ring-[rgba(124,92,252,0.25)]"
              />
              <button
                type="submit"
                disabled={sending || !draft.trim() || !activeSessionId}
                className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#7c5cfc] text-white shadow-[0_0_16px_rgba(124,92,252,0.25)] transition hover:bg-[#9478ff] disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="发送消息"
              >
                {sending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
              </button>
            </form>
          </div>
        </Card>
      </div>
    </div>
  )
}
