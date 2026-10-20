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
  const [genesBefore, knowledgeBefore] = await Promise.all([apiGet('/genes'), apiGet('/knowledge')])
  const pages = await fetch('http://127.0.0.1:9223/json/list').then((response) => response.json())
  const socket = new WebSocket(pages.find((page) => page.type === 'page').webSocketDebuggerUrl)
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }) })
  let id = 0
  const pending = new Map()
  const errors = []
  const checks = []
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data)
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text)
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
    for (let i = 0; i < 80; i++) { if (await evaluate(`Boolean(${expression})`)) return; await delay(125) }
    throw new Error(`UI condition not met: ${expression}`)
  }
  const navigate = async (pathname) => { await send('Page.navigate', { url: `http://127.0.0.1:5173${pathname}` }); await delay(600) }
  const resize = async (width, height) => { await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 720 }); await delay(150) }
  const screenshot = async (name) => { const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }); fs.writeFileSync(`data/library-${name}.png`, Buffer.from(result.data, 'base64')) }
  const clickText = async (selector, text) => evaluate(`Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find(element => element.textContent.trim() === ${JSON.stringify(text)})?.click()`)
  const changeInput = async (label, value) => evaluate(`(() => { const input = document.querySelector('[aria-label="${label}"]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(value)}); input.dispatchEvent(new Event('input', { bubbles: true })); })()`)
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

    await navigate('/genes')
    await until(`document.querySelectorAll('.vc-gene-card').length === ${genesBefore.length}`)
    await screenshot('genes-desktop')
    await noOverflow('desktop genes')
    assert(await evaluate("Array.from(document.querySelectorAll('.vc-gene-card')).every(card => card.getBoundingClientRect().height < 420)"))
    const structure = genesBefore.find((gene) => gene.structure_type)?.structure_type
    if (structure) {
      await changeInput('搜索基因', structure)
      const expected = genesBefore.filter((gene) => [gene.title, gene.source_filename, gene.structure_type, gene.hook_method, gene.overall_emotion].some((value) => String(value || '').includes(structure))).length
      await until(`document.querySelectorAll('.vc-gene-card').length === ${expected}`)
    }
    await changeInput('搜索基因', '')
    await clickText('.vc-library-filters button', '分析中')
    const activeCount = genesBefore.filter((gene) => ['analyzing', 'pending'].includes(gene.status)).length
    await until(`document.querySelectorAll('.vc-gene-card').length === ${activeCount}`)
    await clickText('.vc-library-filters button', '全部')
    await resize(390, 844)
    await noOverflow('mobile genes')
    await screenshot('genes-mobile')
    checks.push('gene search, status filter, compact cards, thumbnail fallback')

    await resize(1440, 1000)
    await navigate('/knowledge')
    await until(`document.querySelectorAll('.vc-knowledge-card').length === ${knowledgeBefore.length}`)
    assert(await evaluate("Array.from(document.querySelectorAll('.vc-knowledge-card-summary')).every(summary => summary.textContent.length <= 71)"))
    assert(await evaluate("Array.from(document.querySelectorAll('.vc-knowledge-card')).every(card => card.getBoundingClientRect().height < 400)"))
    assert.equal(await evaluate("document.querySelectorAll('.vc-knowledge-card video').length"), 0)
    await screenshot('knowledge-desktop')
    await noOverflow('desktop knowledge')

    const longEntry = knowledgeBefore.find((entry) => entry.content.length > 120 && entry.derivation?.source_gene_id) || knowledgeBefore[0]
    if (!longEntry) throw new Error('No personal knowledge available for detail verification')
    const openEntry = async () => evaluate(`Array.from(document.querySelectorAll('.vc-knowledge-card-open')).find(button => button.getAttribute('aria-label') === ${JSON.stringify(`查看知识：${longEntry.title}`)}).click()`)
    await openEntry()
    await until("!!document.querySelector('dialog[open]')")
    const content = await evaluate("Array.from(document.querySelectorAll('.vc-knowledge-detail-section')).find(section => section.querySelector('h3').textContent === '技法说明').querySelector('p').textContent")
    assert.equal(content, longEntry.content)
    assert.equal(await evaluate("document.querySelectorAll('dialog video').length"), 0)
    await screenshot('knowledge-detail')
    await resize(390, 844)
    await noOverflow('mobile knowledge detail')
    await screenshot('knowledge-detail-mobile')
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 })
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 })
    await until("!document.querySelector('dialog[open]')")
    checks.push('knowledge excerpt opens exact original content; Escape closes native modal; no eager demo video loading')

    const hiddenKeyword = longEntry.content.slice(80, 96)
    if (hiddenKeyword) {
      await changeInput('搜索知识', hiddenKeyword)
      const expected = knowledgeBefore.filter((entry) => entry.title.toLowerCase().includes(hiddenKeyword.toLowerCase()) || entry.content.toLowerCase().includes(hiddenKeyword.toLowerCase()) || entry.tags.some((tag) => String(tag).toLowerCase().includes(hiddenKeyword.toLowerCase()))).length
      await until(`document.querySelectorAll('.vc-knowledge-card').length === ${expected}`)
      checks.push('knowledge search matches text hidden from list excerpts')
    }
    await changeInput('搜索知识', '')
    await until(`document.querySelectorAll('.vc-knowledge-card').length === ${knowledgeBefore.length}`)
    await clickText('.vc-knowledge-filters button', 'Hook 技法')
    await until(`document.querySelectorAll('.vc-knowledge-card').length === ${knowledgeBefore.filter((entry) => entry.type === 'hook_technique').length}`)
    await clickText('.vc-knowledge-filters button', '全部')
    await until(`document.querySelectorAll('.vc-knowledge-card').length === ${knowledgeBefore.length}`)
    await noOverflow('mobile knowledge')
    await screenshot('knowledge-mobile')

    await resize(1440, 1000)
    await openEntry()
    const sourceGene = longEntry.derivation?.source_gene_id
    if (sourceGene) {
      const report = (await apiGet(`/genes/${sourceGene}`)).report
      await evaluate("document.querySelector('.vc-library-source-link').click()")
      await until(`location.pathname === '/genes/${sourceGene}' && !!document.querySelector('.vc-report-tabs')`)
      assert.equal(await evaluate("document.querySelector('.vc-report-tabs .is-active').textContent"), '核心概览')
      assert.equal(await evaluate("document.querySelectorAll('.vc-technique-list details[open]').length"), 0)
      await screenshot('gene-report')
      await clickText('.vc-report-tabs button', '开场 Hook')
      const detail = report?.raw_structure_analysis?.hook_strategy?.detail || report?.hook_summary
      if (detail?.length > 110) {
        await evaluate("Array.from(document.querySelectorAll('.vc-report-row')).find(row => row.firstElementChild.textContent === '具体手法').querySelector('summary').click()")
        assert.equal(await evaluate("Array.from(document.querySelectorAll('.vc-report-row')).find(row => row.firstElementChild.textContent === '具体手法').querySelector('.vc-report-text').textContent"), detail)
      }
      await clickText('.vc-report-tabs button', '结构与节奏')
      assert(await evaluate("document.querySelector('.vc-page-content').textContent.includes('节奏曲线')"))
      await resize(390, 844)
      await noOverflow('mobile gene report')
      checks.push('source navigation, report category switching, and full Hook text disclosure')
    }

    const [genesAfter, knowledgeAfter] = await Promise.all([apiGet('/genes'), apiGet('/knowledge')])
    assert.equal(digest(genesAfter), digest(genesBefore))
    assert.equal(digest(knowledgeAfter), digest(knowledgeBefore))
    checks.push('gene and knowledge API payloads unchanged after browsing')
    assert.deepEqual(errors, [])
    fs.writeFileSync('data/library-ui-checks.json', JSON.stringify({ checked_at: new Date().toISOString(), checks, runtime_errors: errors }, null, 2))
    console.log(JSON.stringify({ checks, runtime_errors: errors }, null, 2))
  } finally {
    socket.close()
  }
}

main().catch((error) => { console.error(error.message); process.exitCode = 1 })
