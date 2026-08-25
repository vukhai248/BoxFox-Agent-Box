import { useState, useRef, useEffect } from 'react'
import { ChevronDown, ChevronsUpDown, Check, X } from 'lucide-react'

export interface SelectOption {
  value: string
  label: string
  icon?: React.ReactNode
  description?: string
}

// ---------------------------------------------------------------------------
// 1. Single Custom Select
// ---------------------------------------------------------------------------
interface CustomSelectProps {
  value: string
  onChange: (val: string) => void
  options: SelectOption[] | string[]
  placeholder?: string
  className?: string
  buttonClassName?: string
}

export function CustomSelect({
  value,
  onChange,
  options,
  placeholder = 'Select option...',
  className = '',
  buttonClassName = '',
}: CustomSelectProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Normalize options
  const normalizedOptions: SelectOption[] = options.map((opt) =>
    typeof opt === 'string' ? { value: opt, label: opt } : opt,
  )

  const selected = normalizedOptions.find((o) => o.value === value)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [open])

  return (
    <div ref={ref} className={`relative select-none ${className}`}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex w-full items-center justify-between rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg outline-hidden transition hover:border-brand/50 focus:border-brand cursor-pointer ${buttonClassName}`}
      >
        <div className="flex items-center gap-2 truncate">
          {selected?.icon}
          <span className="truncate">{selected ? selected.label : placeholder}</span>
        </div>
        <ChevronDown
          className={`size-3.5 text-muted shrink-0 transition-transform duration-150 ${
            open ? 'rotate-180 text-fg' : ''
          }`}
        />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-56 overflow-y-auto rounded-xl border border-line bg-panel p-1 shadow-2xl animate-in fade-in zoom-in-95 duration-100">
          {normalizedOptions.map((opt) => {
            const isSelected = opt.value === value
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  onChange(opt.value)
                  setOpen(false)
                }}
                className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs text-left transition cursor-pointer ${
                  isSelected
                    ? 'bg-panel2 text-fg font-medium'
                    : 'text-muted hover:bg-panel2 hover:text-fg'
                }`}
              >
                <div className="flex items-center gap-2 truncate">
                  {opt.icon}
                  <div>
                    <div className="truncate">{opt.label}</div>
                    {opt.description && (
                      <div className="text-[10px] text-muted truncate font-normal">
                        {opt.description}
                      </div>
                    )}
                  </div>
                </div>
                {isSelected && <Check className="size-3.5 text-brand shrink-0 ml-2" />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 2. Tag Multi-Select
// ---------------------------------------------------------------------------
interface TagMultiSelectProps {
  values: string[]
  onChange: (vals: string[]) => void
  options: string[]
  placeholder?: string
  className?: string
}

export function TagMultiSelect({
  values,
  onChange,
  options,
  placeholder = 'Select repositories...',
  className = '',
}: TagMultiSelectProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [open])

  const handleToggle = (opt: string) => {
    if (opt === 'All repositories') {
      onChange(['All repositories'])
      return
    }

    let next = values.filter((v) => v !== 'All repositories')
    if (next.includes(opt)) {
      next = next.filter((v) => v !== opt)
      if (next.length === 0) next = ['All repositories']
    } else {
      next.push(opt)
    }
    onChange(next)
  }

  const handleRemove = (opt: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (values.length <= 1) {
      onChange(['All repositories'])
      return
    }
    onChange(values.filter((v) => v !== opt))
  }

  return (
    <div ref={ref} className={`relative select-none ${className}`}>
      {/* Trigger Box */}
      <div
        onClick={() => setOpen(!open)}
        className="flex min-h-[36px] w-full items-center justify-between rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-xs text-fg outline-hidden transition hover:border-brand/50 focus-within:border-brand cursor-pointer"
      >
        <div className="flex flex-wrap items-center gap-1.5">
          {values.length === 0 ? (
            <span className="text-muted text-xs px-1">{placeholder}</span>
          ) : (
            values.map((val) => (
              <span
                key={val}
                className="inline-flex items-center gap-1 rounded bg-panel border border-line px-2 py-0.5 text-xs font-mono text-fg"
              >
                <span>{val}</span>
                <button
                  type="button"
                  onClick={(e) => handleRemove(val, e)}
                  className="text-muted hover:text-fg transition cursor-pointer p-0.2"
                >
                  <X className="size-3" />
                </button>
              </span>
            ))
          )}
        </div>

        <div className="flex items-center pl-2 text-muted">
          <ChevronsUpDown className="size-3.5" />
        </div>
      </div>

      {/* Floating Dropdown Menu */}
      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-56 overflow-y-auto rounded-xl border border-line bg-panel p-1 shadow-2xl animate-in fade-in zoom-in-95 duration-100">
          {options.map((opt) => {
            const isSelected = values.includes(opt)
            return (
              <button
                key={opt}
                type="button"
                onClick={() => handleToggle(opt)}
                className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs text-left transition cursor-pointer ${
                  isSelected
                    ? 'bg-panel2 text-fg font-medium'
                    : 'text-muted hover:bg-panel2 hover:text-fg'
                }`}
              >
                <span className="font-mono text-xs">{opt}</span>
                {isSelected && <Check className="size-3.5 text-brand shrink-0" />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
