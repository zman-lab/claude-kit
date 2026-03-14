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
