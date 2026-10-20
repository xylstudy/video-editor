const fs = require('node:fs')
const path = require('node:path')

async function main() {
  const account = fs.readFileSync('.local/Video-Claw-账号密码.txt', 'utf8')
  const username = account.match(/用户名：([^\r\n]+)/)?.[1]?.trim()
  const password = account.match(/密码：([^\r\n]+)/)?.[1]?.trim()
  const login = await fetch('http://127.0.0.1:8000/api/auth/login', { method: 'POST', body: new URLSearchParams({ username, password }) })
  if (!login.ok) throw new Error('Local development login failed')
  const token = (await login.json()).access_token
  const response = await fetch('http://127.0.0.1:8000/api/knowledge?scope=system', { headers: { Authorization: `Bearer ${token}` } })
  if (!response.ok) throw new Error('System knowledge request failed')
  const entries = await response.json()
  const missing = entries.filter((entry) => !entry.has_demo)
  const folder = path.resolve('web/backend/storage/knowledge_demos')
  const files = fs.readdirSync(folder).filter((file) => file.endsWith('.mp4'))
  console.log(JSON.stringify({ system_entries: entries.length, with_demo: entries.filter((entry) => entry.has_demo).length, missing_demo_ids: missing.map((entry) => entry.id), local_demo_files: files.length, demo_folder: folder, examples: entries.slice(0, 8).map((entry) => ({ id: entry.id, title: entry.title, type: entry.type, has_demo: entry.has_demo })) }, null, 2))
}

main().catch((error) => { console.error(error.message); process.exitCode = 1 })
