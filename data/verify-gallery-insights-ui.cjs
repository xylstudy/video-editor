const fs = require('node:fs')
const assert = require('node:assert/strict')
const { createHash } = require('node:crypto')
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const digest = (value) => createHash('sha256').update(JSON.stringify(value)).digest('hex')

async function main() {
  const account = fs.readFileSync('.local/Video-Claw-账号密码.txt', 'utf8')
  const username = account.match(/用户名：([^\r\n]+)/)?.[1]?.trim()
  const password = account.match(/密码：([^\r\n]+)/)?.[1]?.trim()
  const login = await fetch('http://127.0.0.1:8000/api/auth/login', { method: 'POST', body: new URLSearchParams({ username, password }) })
  if (!login.ok) throw new Error('Local account login failed')
  const token = (await login.json()).access_token
  const apiGet = async (path) => {
    const response = await fetch(`http://127.0.0.1:8000/api${path}`, { headers: { Authorization: `Bearer ${token}` } })
    if (!response.ok) throw new Error(`Read failed: ${path}`)
    return response.json()
  }
  const [works, insights] = await Promise.all([apiGet('/works'), apiGet('/insights')])
  const pages = await fetch('http://127.0.0.1:9223/json/list').then((response) => response.json())
  const socket = new WebSocket(pages.find((page) => page.type === 'page').webSocketDebuggerUrl)
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }) })
  let id = 0
  let mockInsights = null
  const pending = new Map()
  const errors = []
  const checks = []
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data)
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text)
    if (message.method === 'Fetch.requestPaused') {
      const action = mockInsights ? send('Fetch.fulfillRequest', { requestId: message.params.requestId, responseCode: mockInsights.status || 200, responseHeaders: [{ name: 'Content-Type', value: 'application/json' }], body: Buffer.from(JSON.stringify(mockInsights.data)).toString('base64') }) : send('Fetch.continueRequest', { requestId: message.params.requestId })
      action.catch((error) => errors.push(error.message))
    }
    if (!pending.has(message.id)) return
    const request = pending.get(message.id)
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
    for (let i = 0; i < 100; i++) { if (await evaluate(`Boolean(${expression})`)) return; await delay(125) }
    throw new Error(`UI condition not met: ${expression}`)
  }
  const navigate = async (pathname) => { await send('Page.navigate', { url: `http://127.0.0.1:5173${pathname}` }); await delay(500) }
  const resize = async (width, height) => { await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 720 }); await delay(150) }
  const screenshot = async (name) => { const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }); fs.writeFileSync(`data/gallery-insights-${name}.png`, Buffer.from(result.data, 'base64')) }
  const clickText = async (selector, text) => evaluate(`Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find(element => element.textContent.trim() === ${JSON.stringify(text)})?.click()`)
  const change = async (label, value, select = false) => evaluate(`(() => { const input = document.querySelector('[aria-label="${label}"]'); Object.getOwnPropertyDescriptor(${select ? 'HTMLSelectElement' : 'HTMLInputElement'}.prototype, 'value').set.call(input, ${JSON.stringify(value)}); input.dispatchEvent(new Event('${select ? 'change' : 'input'}', { bubbles: true })); })()`)
  const closeDialog = async () => { await evaluate("document.querySelector('.vc-library-dialog-head button').click()"); await until("!document.querySelector('dialog[open]')") }
  const noOverflow = async (label) => {
    assert(await evaluate("document.documentElement.scrollWidth <= innerWidth + 1 && (!document.querySelector('.vc-app-main') || document.querySelector('.vc-app-main').scrollWidth <= document.querySelector('.vc-app-main').clientWidth + 1) && (!document.querySelector('dialog[open]') || document.querySelector('dialog[open]').scrollWidth <= document.querySelector('dialog[open]').clientWidth + 1)"), label)
    checks.push(`${label}: no horizontal overflow`)
  }

  try {
    await send('Page.enable')
    await send('Runtime.enable')
    await resize(1440, 1000)
    await navigate('/login')
    await evaluate(`(() => { const inputs = document.querySelectorAll('input'); const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; setter.call(inputs[0], ${JSON.stringify(username)}); inputs[0].dispatchEvent(new Event('input', { bubbles: true })); setter.call(inputs[1], ${JSON.stringify(password)}); inputs[1].dispatchEvent(new Event('input', { bubbles: true })); })()`)
    await evaluate("document.querySelector('form').requestSubmit()")
    await until("location.pathname === '/' && !!document.querySelector('.vc-dashboard')")

    await navigate('/works')
    await until(`document.querySelectorAll('.vc-work-gallery-card').length === ${works.length}`)
    assert.equal(await evaluate("document.querySelectorAll('.vc-work-gallery video').length"), 0)
    await until("Array.from(document.querySelectorAll('.vc-work-gallery .vc-media-cover img')).some(image => image.complete && image.naturalWidth > 0)")
    assert(await evaluate("Array.from(document.querySelectorAll('.vc-work-gallery-card')).every(card => card.getBoundingClientRect().height < 400)"))
    await screenshot('works-desktop')
    await noOverflow('desktop portfolio')
    const firstWork = works[0]
    await evaluate(`document.querySelector('[aria-label="对照播放作品：任务 ${firstWork.task_id}"]').click()`)
    await until("document.querySelector('dialog[open] .vc-work-compare')")
    assert.equal(await evaluate("document.querySelectorAll('dialog video').length"), firstWork.reference_material_id ? 2 : 1)
    assert(await evaluate(`document.querySelector('dialog video[aria-label="生成成片"]').getAttribute('src').startsWith('/api/tasks/${firstWork.task_id}/download')`))
    if (firstWork.reference_material_id) assert(await evaluate(`document.querySelector('dialog video[aria-label="参考视频"]').getAttribute('src').startsWith('/api/materials/${firstWork.reference_material_id}/media')`))
    assert(await evaluate(`!!document.querySelector('dialog a[href="/tasks/${firstWork.task_id}"]') && !!document.querySelector('dialog a[href="/projects/${firstWork.project_id}"]') && !!document.querySelector('dialog a[download]')`))
    await until("Array.from(document.querySelectorAll('dialog video')).every(video => video.readyState >= 1 && !video.error)")
    await screenshot('work-comparison')
    await resize(390, 844)
    await noOverflow('mobile portfolio comparison')
    await closeDialog()
    await noOverflow('mobile portfolio')
    await screenshot('works-mobile')
    await change('搜索作品', String(firstWork.task_id))
    const filteredWorks = works.filter((work) => [work.project_name, work.reference_filename, String(work.task_id)].some((value) => String(value || '').includes(String(firstWork.task_id)))).length
    await until(`document.querySelectorAll('.vc-work-gallery-card').length === ${filteredWorks}`)
    await change('搜索作品', '')
    await clickText('.vc-library-filters button', '编辑迁移')
    await until(`document.querySelectorAll('.vc-work-gallery-card').length === ${works.filter((work) => work.pipeline_mode === 'editing_transfer').length}`)
    checks.push('portfolio compact cover gallery, real frame capture, search, mode filter, correct reference/output links, task/project/download actions')

    await resize(1440, 1000)
    await navigate('/insights')
    await until(`document.querySelectorAll('.vc-insight-video-card').length === ${insights.videos.length}`)
    assert.equal(await evaluate("document.querySelectorAll('.vc-insight-metric strong')[0].textContent"), String(insights.sample_size))
    await screenshot('insights-library')
    await noOverflow('desktop insight library')
    const structure = insights.videos.find((video) => video.structure_type)?.structure_type
    if (structure) {
      await change('筛选洞察结构', structure, true)
      await until(`document.querySelectorAll('.vc-insight-video-card').length === ${insights.videos.filter((video) => video.structure_type === structure).length}`)
      await change('筛选洞察结构', '', true)
    }
    const single = insights.video_reports[0]
    const video = insights.videos.find((item) => item.id === single.video_id)
    await evaluate(`document.querySelector('[aria-label="查看独立洞察：${video.id}"]').click()`)
    await until(`document.querySelectorAll('.vc-insight-dimension-card').length === ${single.insights.length}`)
    assert.equal(await evaluate("document.querySelectorAll('.vc-insight-metric strong')[0].textContent"), '1')
    assert.equal(await evaluate("document.querySelectorAll('.vc-insight-metric strong')[1].textContent"), String(video.shot_count))
    await screenshot('insight-single')
    await evaluate("document.querySelector('.vc-insight-dimension-card button').click()")
    await until("document.querySelector('dialog[open]')")
    assert.equal(await evaluate("Array.from(document.querySelectorAll('dialog .vc-knowledge-detail-section')).find(section => section.querySelector('h3').textContent === '完整统计结论').querySelector('p').textContent"), single.insights[0].finding)
    await closeDialog()

    if (video.shots.length > 1) {
      const shot = video.shots[1]
      await evaluate(`document.querySelector('[aria-label="查看镜头 ${shot.index + 1}"]').click()`)
      assert.equal(await evaluate("document.querySelector('.vc-insight-shot-number').textContent"), String(shot.index + 1).padStart(2, '0'))
      await clickText('.vc-insight-shot-preview button', '完整依据')
      await until("document.querySelector('dialog[open]')")
      const expectedSummary = shot.detail?.summary || shot.detail?.visual || '该历史镜头未保存摘要。'
      assert.equal(await evaluate("Array.from(document.querySelectorAll('dialog .vc-knowledge-detail-section')).find(section => section.querySelector('h3').textContent === '画面摘要').querySelector('p').textContent"), expectedSummary)
      await closeDialog()
    }
    await clickText('[aria-label="洞察视图"] button', '综合统计')
    await until(`document.querySelectorAll('.vc-insight-metric strong')[0].textContent === '${insights.sample_size}'`)
    assert.equal(await evaluate("document.querySelectorAll('.vc-insight-dimension-card').length"), insights.insights.length)
    assert(!await evaluate("document.querySelector('.vc-insight-explorer-card > details').open"))
    await screenshot('insights-aggregate')
    await resize(900, 900)
    await noOverflow('tablet aggregate insights')
    await resize(390, 844)
    await noOverflow('mobile aggregate insights')
    await screenshot('insights-mobile')
    await evaluate("document.querySelector('.vc-insight-dimension-card button').click()")
    await noOverflow('mobile dimension detail')
    await screenshot('insight-drawer-mobile')
    await closeDialog()
    checks.push('insight structure filter, independent single-video counters, complete findings, selected-shot evidence, aggregate scope, collapsed explorer')

    await resize(1440, 1000)
    await clickText('[aria-label="洞察视图"] button', '视频特征库')
    await evaluate(`document.querySelector('[aria-label="查看独立洞察：${video.id}"]').click()`)
    await send('Fetch.enable', { patterns: [{ urlPattern: '*/api/insights', requestStage: 'Request' }] })
    mockInsights = { data: { ...insights, video_reports: [] } }
    await clickText('.vc-page-content button', '刷新统计')
    await until("document.querySelector('.vc-page-content').textContent.includes('缺少独立统计')")
    assert.equal(await evaluate("document.querySelectorAll('.vc-insight-dimension-card').length"), 0)
    mockInsights = { data: { sample_size: 0, videos: [], video_reports: [], insights: [], generated_at: '' } }
    await clickText('.vc-page-content button', '刷新统计')
    await until("document.querySelector('.vc-page-content').textContent.includes('还没有个人洞察')")
    mockInsights = { status: 503, data: { detail: '模拟洞察服务暂不可用' } }
    await clickText('.vc-page-content button', '刷新统计')
    await until("document.querySelector('.vc-page-content').textContent.includes('模拟洞察服务暂不可用')")
    mockInsights = null
    await send('Fetch.disable')
    await clickText('.vc-page-content button', '刷新统计')
    await until(`document.querySelectorAll('.vc-insight-dimension-card').length === ${single.insights.length}`)
    checks.push('mocked missing single report does not use aggregate statistics; empty/error/recovery states')

    await navigate('/knowledge')
    await until("document.querySelector('.vc-knowledge-card-open')")
    await evaluate("document.querySelector('.vc-knowledge-card-open').click()")
    await until("document.querySelector('dialog[open]')")
    await closeDialog()
    checks.push('shared knowledge detail remains usable')

    const [worksAfter, insightsAfter] = await Promise.all([apiGet('/works'), apiGet('/insights')])
    assert.equal(digest(worksAfter), digest(works))
    assert.equal(insightsAfter.sample_size, insights.sample_size)
    assert.deepEqual(insightsAfter.videos.map((item) => [item.id, item.shot_count, item.duration]), insights.videos.map((item) => [item.id, item.shot_count, item.duration]))
    assert.deepEqual(errors, [])
    fs.writeFileSync('data/gallery-insights-checks.json', JSON.stringify({ checked_at: new Date().toISOString(), checks, runtime_errors: errors }, null, 2))
    console.log(JSON.stringify({ checks, runtime_errors: errors }, null, 2))
  } finally {
    await send('Fetch.disable').catch(() => {})
    socket.close()
  }
}

main().catch((error) => { console.error(error.message); process.exitCode = 1 })
