import { useState, useEffect, useCallback } from 'react'

/**
 * textarea에서 {# 입력 시 파일 자동완성 드롭다운
 * @param {Object} textareaRef - textarea ref
 * @param {string} value - textarea value
 * @param {Function} onChange - value 변경 콜백
 * @param {Array} files - [{filename}] 후보 파일 목록
 */
export function useFileAutocomplete(textareaRef, value, onChange, files = []) {
  const [show, setShow] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [position, setPosition] = useState({ top: 0, left: 0 })

  const filtered = files.filter(f =>
    f.filename.toLowerCase().includes(query.toLowerCase())
  )

  const checkTrigger = useCallback(() => {
    const textarea = textareaRef.current
    if (!textarea) return

    const cursorPos = textarea.selectionStart
    const textBefore = value.slice(0, cursorPos)

    // {# 패턴 감지
    const triggerMatch = textBefore.match(/\{#([^}]*)$/)

    if (triggerMatch) {
      setQuery(triggerMatch[1])
      setShow(true)
      setSelectedIdx(0)

      // 드롭다운 위치 계산 (textarea 기준 상대 좌표)
      const rect = textarea.getBoundingClientRect()
      setPosition({ top: rect.height + 4, left: 0 })
    } else {
      setShow(false)
    }
  }, [value, textareaRef])

  // value 변경 시 체크
  useEffect(() => {
    checkTrigger()
  }, [value, checkTrigger])

  const select = useCallback((file) => {
    const textarea = textareaRef.current
    if (!textarea) return

    const cursorPos = textarea.selectionStart
    const textBefore = value.slice(0, cursorPos)
    const textAfter = value.slice(cursorPos)

    // {#query 부분을 {#filename}으로 교체
    const triggerIdx = textBefore.lastIndexOf('{#')
    if (triggerIdx === -1) return

    const newText = textBefore.slice(0, triggerIdx) + `{#${file.filename}}` + textAfter
    onChange(newText)
    setShow(false)

    // 커서를 } 뒤로
    setTimeout(() => {
      const newPos = triggerIdx + file.filename.length + 3 // {# + filename + }
      textarea.setSelectionRange(newPos, newPos)
      textarea.focus()
    }, 0)
  }, [value, onChange, textareaRef])

  const handleKeyDown = useCallback((e) => {
    if (!show || filtered.length === 0) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIdx(i => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && show) {
      e.preventDefault()
      select(filtered[selectedIdx])
    } else if (e.key === 'Escape') {
      setShow(false)
    }
  }, [show, filtered, selectedIdx, select])

  return { show, filtered, selectedIdx, position, select, handleKeyDown }
}
