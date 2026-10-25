const fs = require('node:fs')
const assert = require('node:assert/strict')
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function main() {
  const account = fs.readFileSync('.local/Video-Claw-账号密码.txt', 'utf8')
  const username = account.match(/用户名：([^\r\n]+)/)?.[1]?.trim()
  const password = account.match(/密码：([^\r\n]+)/)?.[1]?.trim()
  const login = await fetch('http://127.0.0.1:8000/api/auth/login', { method: 'POST', body: new URLSearchParams({ username, password }) })
  assert(login.ok)
  const token = (await login.json()).access_token
  const headers = { Authorization: `Bearer ${token}` }
  const entries = await fetch('http://127.0.0.1:8000/api/knowledge?scope=system', { headers }).then((response) => response.json())
  const builtin = entries.filter((entry) => /^k_\d+$/.test(entry.id))
  assert.equal(builtin.length, 52)
  assert(builtin.every((entry) => entry.has_demo))
  const checks = []
  for (const entry of builtin) {
    const response = await fetch(`http://127.0.0.1:8000/api/knowledge/${entry.id}/demo`, { headers: { ...headers, Range: 'bytes=0-1023' } })
    assert.equal(response.status, 206, entry.id)
    assert(response.headers.get('content-type').includes('video/mp4'), entry.id)
    assert.equal((await response.arrayBuffer()).byteLength, 1024, entry.id)
  }
  checks.push('all 52 built-in demos exist and serve video/mp4 with HTTP Range support')

  const pages = await fetch('http://127.0.0.1:9223/json/list').then((response) => response.json())
  const socket = new WebSocket(pages.find((page) => page.type === 'page').webSocketDebuggerUrl)
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }) })
  let id = 0
  const pending = new Map()
  const errors = []
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data)
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text)
    const request = pending.get(message.id)
    if (!request) return
    pending.delete(message.id)
    clearTimeout(request.timeout)
    message.error ? request.reject(new Error(message.error.message)) : request.resolve(message.result)
  })
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const requestId = ++id
    pending.set(requestId, { resolve, reject, timeout: setTimeout(() => { pending.delete(requestId); reject(new Error(`${method} timed out`)) }, 15000) })
    socket.send(JSON.stringify({ id: requestId, method, params }))
  })
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text)
    return result.result.value
  }
  const until = async (expression) => {
    for (let attempt = 0; attempt < 80; attempt++) { if (await evaluate(`Boolean(${expression})`)) return; await delay(125) }
    throw new Error(`UI condition not met: ${expression}`)
  }
  const screenshot = async (name) => {
    const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    fs.writeFileSync(`data/system-demos-${name}.png`, Buffer.from(result.data, 'base64'))
  }

  try {
    await send('Page.enable')
    await send('Runtime.enable')
    await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
    await send('Page.navigate', { url: 'http://127.0.0.1:5173/login' })
    await until("document.querySelector('input')")
    await evaluate(`(() => { const inputs = document.querySelectorAll('input'); const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; setter.call(inputs[0], ${JSON.stringify(username)}); inputs[0].dispatchEvent(new Event('input', { bubbles: true })); setter.call(inputs[1], ${JSON.stringify(password)}); inputs[1].dispatchEvent(new Event('input', { bubbles: true })); })()`)
    await evaluate("document.querySelector('form').requestSubmit()")
    await until("location.pathname === '/' && document.querySelector('.vc-dashboard')")
    await send('Page.navigate', { url: 'http://127.0.0.1:5173/knowledge' })
    await until("document.querySelector('.vc-knowledge-card')")
    await evaluate("Array.from(document.querySelectorAll('.vc-page-content button')).find(button => button.textContent.trim() === '系统技法').click()")
    await until("document.querySelectorAll('.vc-library-demo-button').length === 52")
    assert.equal(await evaluate("document.querySelectorAll('.vc-knowledge-card video').length"), 0)
    assert(await evaluate("document.querySelector('.vc-page-content').textContent.includes('52 个视频演示')"))
    await screenshot('list-desktop')

    for (const type of ['transition_type', 'effect_type', 'editing_technique', 'packaging_style']) {
      const entry = builtin.find((item) => item.type === type)
      assert(entry, type)
      await evaluate(`Array.from(document.querySelectorAll('.vc-library-demo-button')).find(button => button.getAttribute('aria-label') === ${JSON.stringify(`播放技法演示：${entry.title}`)}).click()`)
      await until("document.querySelector('dialog[open] video')")
      assert(await evaluate(`document.querySelector('dialog video').getAttribute('src').startsWith('/api/knowledge/${entry.id}/demo')`))
      await until("document.querySelector('dialog video').readyState >= 2 && !document.querySelector('dialog video').error")
      await evaluate("(async () => { const video = document.querySelector('dialog video'); video.muted = true; await video.play(); })()")
      await until("document.querySelector('dialog video').currentTime > .5")
      await evaluate("document.querySelector('dialog video').pause()")
      if (type === 'packaging_style') {
        await screenshot('player-desktop')
        await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true })
        assert(await evaluate("document.querySelector('dialog').scrollWidth <= document.querySelector('dialog').clientWidth + 1"))
        await screenshot('player-mobile')
      }
      await evaluate("document.querySelector('.vc-library-dialog-head button').click()")
      await until("!document.querySelector('dialog[open]')")
      checks.push(`${type}: direct card action opens the correct demo and playback advances`)
    }
    assert(await evaluate("document.querySelector('.vc-app-main').scrollWidth <= document.querySelector('.vc-app-main').clientWidth + 1"))
    await screenshot('list-mobile')
    const entry = builtin[0]
    await evaluate(`Array.from(document.querySelectorAll('.vc-knowledge-card-open')).find(button => button.getAttribute('aria-label') === ${JSON.stringify(`查看知识：${entry.title}`)}).click()`)
    await until("document.querySelector('dialog[open]')")
    assert.equal(await evaluate("document.querySelectorAll('dialog video').length"), 0)
    await evaluate("Array.from(document.querySelectorAll('dialog button')).find(button => button.textContent.trim() === '播放演示').click()")
    await until("document.querySelector('dialog video')?.readyState >= 2")
    await evaluate("document.querySelector('dialog video').pause()")
    checks.push('normal detail opens without autoplay; in-detail play action still works; mobile layouts fit')
    assert.deepEqual(errors, [])
    const report = { checked_at: new Date().toISOString(), system_entries: entries.length, playable_builtin_demos: builtin.length, entries_without_demo: entries.filter((item) => !item.has_demo).map((item) => ({ id: item.id, title: item.title })), checks, runtime_errors: errors }
    fs.writeFileSync('data/system-demos-checks.json', JSON.stringify(report, null, 2))
    console.log(JSON.stringify(report, null, 2))
  } finally {
    socket.close()
  }
}

main().catch((error) => { console.error(error.message); process.exitCode = 1 })
