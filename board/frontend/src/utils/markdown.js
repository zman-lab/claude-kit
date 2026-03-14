import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'

marked.setOptions({
  highlight: (code, lang) => {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value
    }
    return hljs.highlightAuto(code).value
  },
  breaks: true,
  gfm: true,
})

export function renderMarkdown(text) {
  if (!text) return ''
  return marked.parse(text)
}

/**
 * {#파일명} 패턴을 첨부파일 링크/이미지로 치환
 * @param {string} text - 원본 마크다운
 * @param {Array} attachments - [{id, filename, mime_type, stored_name}]
 * @returns {string} 치환된 마크다운
 */
export function replaceFileTags(text, attachments = []) {
  if (!text || !attachments.length) return text

  const attMap = {}
  attachments.forEach(a => { attMap[a.filename] = a })

  return text.replace(/\{#([^}]+)\}/g, (match, filename) => {
    const att = attMap[filename]
    if (!att) return match

    const downloadUrl = `/api/attachments/${att.id}/download`
    const isImage = /\.(jpg|jpeg|png|gif|webp|svg)$/i.test(filename) ||
                    (att.mime_type && att.mime_type.startsWith('image/'))

    if (isImage) {
      return `![${filename}](${downloadUrl})`
    } else {
      return `[📎 ${filename}](${downloadUrl})`
    }
  })
}

// 마크다운 문법 제거 (목록 미리보기용)
export function stripMarkdown(text) {
  if (!text) return ''
  return text
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`[^`]+`/g, '')
    .replace(/#{1,6}\s/g, '')
    .replace(/[*_~]{1,3}/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/>\s?/g, '')
    .replace(/[-*+]\s/g, '')
    .replace(/\d+\.\s/g, '')
    .replace(/\n+/g, ' ')
    .trim()
    .slice(0, 200)
}
