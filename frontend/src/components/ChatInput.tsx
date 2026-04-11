import { useState, useRef, useCallback } from 'react'
import { Send } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  onSend:    (message: string) => void
  isLoading: boolean
  disabled?: boolean
}

export function ChatInput({ onSend, isLoading, disabled }: Props) {
  const [value, setValue]     = useState('')
  const textareaRef           = useRef<HTMLTextAreaElement>(null)

  const submit = useCallback(() => {
    const trimmed = value.trim()
    if (!trimmed || isLoading || disabled) return
    onSend(trimmed)
    setValue('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }, [value, isLoading, disabled, onSend])

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function onInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setValue(e.target.value)
    const ta = textareaRef.current
    if (ta) {
      ta.style.height = 'auto'
      ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`
    }
  }

  const canSend = value.trim().length > 0 && !isLoading && !disabled

  return (
    <div className="border-t border-border-default bg-canvas-default px-4 py-3">
      <div className="flex items-end gap-2 rounded-xl border border-border-default bg-canvas-overlay px-3 py-2.5 transition-colors focus-within:border-accent-fg">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={onInput}
          onKeyDown={onKeyDown}
          placeholder="Ask about the codebase… (↵ to send, Shift+↵ for newline)"
          rows={1}
          disabled={disabled}
          className="flex-1 resize-none bg-transparent text-sm text-fg-default placeholder-fg-subtle outline-none disabled:opacity-50"
          style={{ maxHeight: '200px' }}
        />

        <div className="flex flex-shrink-0 items-center gap-1 pb-0.5">
          <button
            onClick={submit}
            disabled={!canSend}
            title="Send (↵)"
            className={cn(
              'flex h-7 w-7 items-center justify-center rounded-lg transition-all',
              canSend
                ? 'bg-accent-emphasis text-fg-onEmphasis hover:opacity-90'
                : 'cursor-not-allowed bg-canvas-subtle text-fg-subtle',
            )}
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <p className="mt-1.5 text-center text-[10px] text-fg-subtle">
        Responses are grounded in indexed code — always verify critical details
      </p>
    </div>
  )
}
