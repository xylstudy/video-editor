const fs = require('node:fs')
const assert = require('node:assert/strict')
const path = require('node:path')
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function main() {
  const pages = await fetch('http://127.0.0.1:9223/json/list').then((response) => response.json())
  const page = pages.find((item) => item.type === 'page')
  if (!page) throw new Error('Local preview browser is unavailable')
  const socket = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true })
    socket.addEventListener('error', reject, { once: true })
  })
  let id = 0
  const pending = new Map()
  const errors = []
  const checks = []
  const fixturePath = path.resolve('web/frontend/ui-storyboard-preview.html')
  let fixtureCreated = false
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text)
    if (!pending.has(message.id)) return
    const { resolve, reject, timeout } = pending.get(message.id)
    pending.delete(message.id)
    clearTimeout(timeout)
    message.error ? reject(new Error(message.error.message)) : resolve(message.result)
  })
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const requestId = ++id
    const timeout = setTimeout(() => { pending.delete(requestId); reject(new Error(`${method} timed out`)) }, 15000)
    pending.set(requestId, { resolve, reject, timeout })
    socket.send(JSON.stringify({ id: requestId, method, params }))
  })
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text)
    return result.result.value
  }
  const until = async (expression) => {
    for (let attempt = 0; attempt < 60; attempt++) {
      if (await evaluate(`Boolean(${expression})`)) return
      await delay(150)
    }
    throw new Error(`UI condition not met: ${expression}`)
  }
  const navigate = async (url) => { await send('Page.navigate', { url }); await delay(800) }
  const resize = async (width, height, mobile = false) => { await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile }); await delay(200) }
  const screenshot = async (name) => {
    const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    fs.writeFileSync(`data/frontend-distilled-${name}.png`, Buffer.from(result.data, 'base64'))
  }
  const noOverflow = async (name) => {
    assert(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), `${name} has horizontal overflow`)
    checks.push(`${name}: no horizontal overflow`)
  }
  const prepareVideoFrames = async (selector) => {
    await until(`Array.from(document.querySelectorAll(${JSON.stringify(selector)})).every(video => Number.isFinite(video.duration) && video.duration > 0)`)
    await evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).forEach(video => { video.currentTime = Math.min(.5, video.duration / 2) })`)
    await until(`Array.from(document.querySelectorAll(${JSON.stringify(selector)})).every(video => !video.seeking && video.readyState >= 2 && !video.error)`)
  }
  const clickText = async (text) => evaluate(`Array.from(document.querySelectorAll('button')).find(button => button.textContent.trim() === ${JSON.stringify(text)})?.click()`)
  const changeInput = async (label, value, select = false) => evaluate(`(() => {
    const element = document.querySelector('[aria-label="${label}"]');
    const setter = Object.getOwnPropertyDescriptor(${select ? 'HTMLSelectElement' : 'HTMLInputElement'}.prototype, 'value').set;
    setter.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event('${select ? 'change' : 'input'}', { bubbles: true }));
  })()`)

  try {
    await send('Page.enable')
    await send('Runtime.enable')
    await send('Network.enable')
    await resize(1440, 1000)
    await navigate('http://127.0.0.1:5173/login')
    const account = fs.readFileSync('.local/Video-Claw-账号密码.txt', 'utf8')
    const username = account.match(/用户名：([^\r\n]+)/)?.[1]?.trim()
    const password = account.match(/密码：([^\r\n]+)/)?.[1]?.trim()
    if (!username || !password) throw new Error('Local development account is incomplete')
    await evaluate(`(() => {
      const inputs = document.querySelectorAll('input');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(inputs[0], ${JSON.stringify(username)}); inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
      setter.call(inputs[1], ${JSON.stringify(password)}); inputs[1].dispatchEvent(new Event('input', { bubbles: true }));
    })()`)
    await evaluate("document.querySelector('form').requestSubmit()")
    await until("location.pathname === '/' && document.querySelector('.vc-dashboard') && document.querySelector('.vc-service-pill.is-online')")
    checks.push('login and live backend health indicator')
    await screenshot('dashboard')

    await resize(390, 844, true)
    await noOverflow('mobile dashboard')
    await evaluate("document.querySelector('.vc-mobile-menu').click()")
    await until("!!document.querySelector('.vc-mobile-drawer')")
    assert(await evaluate("Array.from(document.querySelectorAll('.vc-mobile-drawer .vc-nav-copy')).every(element => getComputedStyle(element).display !== 'none')"))
    assert(await evaluate("getComputedStyle(document.querySelector('.vc-mobile-drawer .vc-profile-chip button')).display !== 'none'"))
    await screenshot('mobile-navigation')
    await evaluate("document.querySelector('.vc-mobile-drawer a[href=\"/projects\"]').click()")
    await until("location.pathname === '/projects' && !document.querySelector('.vc-mobile-drawer')")
    checks.push('mobile menu labels, logout visibility, and navigation close')
    await noOverflow('mobile project list')

    await resize(900, 900)
    await noOverflow('tablet project list')
    assert(await evaluate("getComputedStyle(document.querySelector('.vc-app-sidebar .vc-profile-chip button')).display !== 'none'"))
    checks.push('collapsed tablet sidebar retains logout action')

    await resize(1440, 1000)
    await until("!!document.querySelector('a[href^=\"/projects/\"]')")
    await evaluate("Array.from(document.querySelectorAll('a[href^=\"/projects/\"]')).at(-1).click()")
    await until("!!document.querySelector('.vc-material-preview')")
    await noOverflow('desktop project detail')
    await prepareVideoFrames('.vc-material-preview video')
    await screenshot('project-detail')
    const materials = await evaluate("document.querySelectorAll('.vc-material-select').length")
    if (materials > 1) {
      await evaluate("Array.from(document.querySelectorAll('.vc-material-select')).at(-1).click()")
      assert(await evaluate("document.querySelector('.vc-material-preview-head p').textContent === '素材预览'"))
      checks.push('project media selection switches preview')
    }
    await resize(390, 844, true)
    await noOverflow('mobile project detail')

    await resize(1440, 1000)
    await navigate('http://127.0.0.1:5173/works')
    await until("!!document.querySelector('.vc-work-card')")
    await prepareVideoFrames('.vc-work-card:first-child video')
    await evaluate("(async () => { const video = document.querySelector('.vc-work-card video'); video.muted = true; await video.play(); })()")
    await until("document.querySelector('.vc-work-card video').currentTime > .6")
    await evaluate("document.querySelector('.vc-work-card video').pause()")
    checks.push('reference and generated videos decode; reference playback advances')
    await screenshot('works')
    await noOverflow('desktop works')
    assert(await evaluate("document.querySelectorAll('.vc-work-card video').length >= 2"))
    await resize(390, 844, true)
    await noOverflow('mobile works')

    await resize(1440, 1000)
    if (fs.existsSync(fixturePath)) throw new Error('Refusing to overwrite an existing preview fixture')
    fs.copyFileSync('data/fixtures/storyboard-ui.html', fixturePath)
    fixtureCreated = true
    await navigate('http://127.0.0.1:5173/ui-storyboard-preview.html')
    await until("document.querySelectorAll('.vc-shot-item').length === 3")
    await prepareVideoFrames('.vc-shot-screen video')
    await screenshot('storyboard')
    await evaluate("document.querySelectorAll('.vc-shot-item')[1].click()")
    await changeInput('字幕', '验证字幕')
    await changeInput('时长（秒）', '2.5')
    await changeInput('转场', 'fade', true)
    await clickText('下移')
    assert(await evaluate("document.querySelectorAll('.vc-shot-item')[2].getAttribute('aria-pressed') === 'true'"))
    assert.equal(await evaluate("document.querySelector('[aria-label=字幕]').value"), '验证字幕')
    await evaluate("document.querySelectorAll('.vc-shot-item')[0].click()")
    await clickText('删除')
    assert.equal(await evaluate("document.querySelectorAll('.vc-shot-item').length"), 2)
    await evaluate('window.__storyboardPreview.rejectNextSave = true')
    await clickText('保存草案')
    await until("document.querySelector('.vc-studio-feedback')?.textContent.includes('验证保存失败')")
    assert.equal(await evaluate("document.querySelectorAll('.vc-shot-item').length"), 2)
    await clickText('保存草案')
    await until("document.querySelector('.vc-studio-feedback')?.textContent.includes('第 2 版已保存')")
    const saved = await evaluate('window.__storyboardPreview.requests.at(-1).body')
    assert.deepEqual(saved.storyboard.map((frame) => frame.draft_id), ['preview-2', 'preview-1'])
    assert.equal(saved.storyboard[1].subtitle_text, '验证字幕')
    assert.equal(saved.storyboard[1].duration, 2.5)
    assert.equal(saved.storyboard[1].transition, 'fade')
    await clickText('确认并开始渲染')
    await until('window.__storyboardPreview.confirmed === true')
    assert.deepEqual(await evaluate('window.__storyboardPreview.requests.slice(-2).map(request => request.method)'), ['put', 'post'])
    checks.push('storyboard selection, editing, reorder, removal, failed-save recovery, save payload, and save-before-confirm (mock requests only)')
    await resize(390, 844, true)
    await noOverflow('mobile storyboard')
    await screenshot('storyboard-mobile')

    await resize(1440, 1000)
    await send('Network.setBlockedURLs', { urls: ['*127.0.0.1:5173/api/health*'] })
    await navigate('http://127.0.0.1:5173/')
    await until("!!document.querySelector('.vc-service-pill.is-offline')")
    checks.push('unavailable backend health changes indicator to offline')
    await send('Network.setBlockedURLs', { urls: [] })
    await send('Page.reload')
    await until("!!document.querySelector('.vc-service-pill.is-online')")
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'k', code: 'KeyK', modifiers: 2 })
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'k', code: 'KeyK', modifiers: 2 })
    await until("location.pathname === '/assistant'")
    checks.push('Ctrl+K opens assistant')

    await evaluate("document.querySelector('.vc-profile-chip button').click()")
    await until("location.pathname === '/login'")
    await screenshot('login')
    assert.deepEqual(errors, [], 'browser runtime exceptions')
    fs.writeFileSync('data/frontend-distilled-checks.json', JSON.stringify({ checked_at: new Date().toISOString(), checks, runtime_errors: errors }, null, 2))
    console.log(JSON.stringify({ checks, runtime_errors: errors }, null, 2))
  } finally {
    if (fixtureCreated) fs.unlinkSync(fixturePath)
    socket.close()
  }
}

main().catch((error) => { console.error(error.message); process.exitCode = 1 })
