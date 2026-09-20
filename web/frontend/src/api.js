import axios from 'axios'
import { getToken, removeToken, removeStoredUser } from './auth.js'

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      removeToken()
      removeStoredUser()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api

/**
 * 构造带鉴权 token 的媒体 URL。
 * <video> / <a download> 无法携带 Authorization 头，媒体端点支持 ?token= 查询参数。
 */
export function mediaUrl(path) {
  const token = getToken()
  const sep = path.includes('?') ? '&' : '?'
  return `/api${path}${sep}token=${encodeURIComponent(token || '')}`
}

export function login(username, password) {
  const params = new URLSearchParams()
  params.append('username', username)
  params.append('password', password)
  return axios.post('/api/auth/login', params, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
}

export function register(username, password, email) {
  return axios.post('/api/auth/register', { username, password, email })
}

export function getMe() {
  return api.get('/auth/me')
}

export function listProjects() {
  return api.get('/projects')
}

export function createProject(data) {
  return api.post('/projects', data)
}

export function getProject(id) {
  return api.get(`/projects/${id}`)
}

export function deleteProject(id) {
  return api.delete(`/projects/${id}`)
}

export function listMaterials(projectId) {
  return api.get(`/materials/project/${projectId}`)
}

export function uploadMaterial(projectId, file, type) {
  const form = new FormData()
  form.append('project_id', projectId)
  form.append('type', type)
  form.append('file', file)
  return api.post('/materials/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function deleteMaterial(id) {
  return api.delete(`/materials/${id}`)
}

export function listTasks(projectId) {
  return api.get(`/tasks/project/${projectId}`)
}

export function createTask(projectId, type = 'end_to_end') {
  return api.post(`/tasks/project/${projectId}`, { type })
}

export function getTask(taskId) {
  return api.get(`/tasks/${taskId}`)
}

export function getTaskEvaluation(taskId) {
  return api.get(`/tasks/${taskId}/evaluation`)
}

export function getStoryboard(taskId) {
  return api.get(`/tasks/${taskId}/storyboard`)
}

export function updateStoryboard(taskId, data) {
  return api.put(`/tasks/${taskId}/storyboard`, data)
}

export function confirmStoryboard(taskId) {
  return api.post(`/tasks/${taskId}/storyboard/confirm`)
}

export function deleteTask(taskId) {
  return api.delete(`/tasks/${taskId}`)
}

export function downloadTaskResult(taskId) {
  return api.get(`/tasks/${taskId}/download`, { responseType: 'blob' })
}

export function listApiKeys() {
  return api.get('/api-keys')
}

export function saveApiKey(provider, keyValue) {
  return api.post('/api-keys', { provider, key_value: keyValue })
}

export function deleteApiKey(provider) {
  return api.delete(`/api-keys/${provider}`)
}

/* ---------- 模型配置 ---------- */
export function listModels() {
  return api.get('/models')
}

export function createModel(data) {
  return api.post('/models', data)
}

export function updateModel(id, data) {
  return api.put(`/models/${id}`, data)
}

export function deleteModel(id) {
  return api.delete(`/models/${id}`)
}

export function testModel(data) {
  return api.post('/models/test', data)
}

export function setDefaultModel(id, purpose) {
  return api.post(`/models/${id}/default/${purpose}`)
}

/* ---------- 视频基因库 ---------- */
export function listGenes() {
  return api.get('/genes')
}

export function createGene(title, file, useSample = false) {
  const form = new FormData()
  form.append('title', title)
  form.append('use_sample', useSample ? 'true' : 'false')
  if (file) form.append('file', file)
  return api.post('/genes', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function getGene(id) {
  return api.get(`/genes/${id}`)
}

export function deleteGene(id) {
  return api.delete(`/genes/${id}`)
}

export function extractGeneKnowledge(id) {
  return api.post(`/genes/${id}/extract-knowledge`)
}

/* ---------- 知识库 ---------- */
export function listKnowledge(params = {}) {
  return api.get('/knowledge', { params })
}

export function deleteKnowledge(id) {
  return api.delete(`/knowledge/${encodeURIComponent(id)}`)
}

/* ---------- 作品集 ---------- */
export function listWorks() {
  return api.get('/works')
}

/* ---------- 工作台统计 ---------- */
export function getStats() {
  return api.get('/stats')
}

/* ---------- 智能助手 ---------- */
export function listChatSessions() {
  return api.get('/chat/sessions')
}

export function createChatSession(data = {}) {
  return api.post('/chat/sessions', data)
}

export function listChatMessages(sessionId, params = {}) {
  return api.get(`/chat/sessions/${sessionId}/messages`, { params })
}

export function updateChatContext(sessionId, context) {
  return api.patch(`/chat/sessions/${sessionId}/context`, { context })
}

export function clearChatContext(sessionId) {
  return api.delete(`/chat/sessions/${sessionId}/context`)
}

export function sendChatMessage(sessionId, content, context = {}) {
  return api.post(`/chat/sessions/${sessionId}/messages`, { content, context })
}

export function uploadChatAttachment(sessionId, file) {
  const form = new FormData()
  form.append('file', file)
  return api.post(`/chat/sessions/${sessionId}/attachments`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
