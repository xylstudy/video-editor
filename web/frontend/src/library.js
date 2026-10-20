// Presentation excerpts only. Source reports and knowledge content stay intact.
export function compactText(value, limit = 64) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit).trimEnd()}…` : text
}

export function shortHeading(value, limit = 22) {
  const text = String(value ?? '').trim()
  const heading = text.split(/[：:]/)[0]
  return compactText(heading || text, limit)
}

export function firstSentence(value, limit = 70) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  const sentence = text.match(/^.*?[。！？]/)?.[0]
  return compactText(sentence || text, limit)
}

export function geneDisplayTitle(gene) {
  const title = String(gene.title || '').trim()
  return /^[a-f\d]{24,}(?:\.mp4)?$/i.test(title)
    ? `${gene.structure_type || '视频结构'}参考 · #${gene.id}`
    : title || `参考视频 #${gene.id}`
}
