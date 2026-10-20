const fs = require('fs')

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function connect() {
  const pages = await fetch('http://127.0.0.1:9223/json/list').then((response) => response.json())
  const page = pages.find((item) => item.type === 'page')
  if (!page) throw new Error('No browser page found')
  const socket = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true })
    socket.addEventListener('error', reject, { once: true })
  })
  let id = 0
  const waiting = new Map()
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    if (!message.id || !waiting.has(message.id)) return
    const { resolve, reject } = waiting.get(message.id)
    waiting.delete(message.id)
    if (message.error) reject(new Error(message.error.message))
    else resolve(message.result)
  })
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const requestId = ++id
    waiting.set(requestId, { resolve, reject })
    socket.send(JSON.stringify({ id: requestId, method, params }))
  })
  return { socket, send }
}

async function main() {
  const account = fs.readFileSync('.local/Video-Claw-账号密码.txt', 'utf8')
  const username = account.match(/用户名：([^\r\n]+)/)?.[1]?.trim()
  const password = account.match(/密码：([^\r\n]+)/)?.[1]?.trim()
  if (!username || !password) throw new Error('Local development account is incomplete')

  const { socket, send } = await connect()
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
  await send('Page.navigate', { url: 'http://127.0.0.1:5173/login' })
  await delay(1300)
  const loginExpression = `(() => {
    const fields = document.querySelectorAll('input');
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setValue.call(fields[0], ${JSON.stringify(username)});
    fields[0].dispatchEvent(new Event('input', { bubbles: true }));
    setValue.call(fields[1], ${JSON.stringify(password)});
    fields[1].dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('form').requestSubmit();
  })()`
  await send('Runtime.evaluate', { expression: loginExpression })
  await delay(2400)
  const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  fs.writeFileSync('data/frontend-distilled-dashboard.png', Buffer.from(result.data, 'base64'))

  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true })
  await delay(500)
  const mobile = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  fs.writeFileSync('data/frontend-distilled-mobile.png', Buffer.from(mobile.data, 'base64'))
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })

  await send('Page.navigate', { url: 'http://127.0.0.1:5173/projects' })
  await delay(1500)
  const projects = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  fs.writeFileSync('data/frontend-distilled-projects.png', Buffer.from(projects.data, 'base64'))

  await send('Runtime.evaluate', { expression: "document.querySelector('.vc-profile-chip button').click()" })
  await send('Page.navigate', { url: 'http://127.0.0.1:5173/login' })
  await delay(1100)
  const login = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  fs.writeFileSync('data/frontend-distilled-login.png', Buffer.from(login.data, 'base64'))

  process.stdout.write('captured dashboard, projects, and login')
  socket.close()
}

main().catch((error) => {
  process.stderr.write(error.stack || String(error))
  process.exitCode = 1
})
