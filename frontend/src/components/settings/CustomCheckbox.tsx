import { Check } from 'lucide-react'

export interface CustomCheckboxProps {
  checked: boolean
  onChange: () => void
  label?: string
  description?: string
  className?: string
}

export function CustomCheckbox({
  checked,
  onChange,
  label,
  description,
  className = '',
}: CustomCheckboxProps) {
  return (
    <label
      onClick={(e) => {
        e.preventDefault()
        onChange()
      }}
      className={`flex items-center gap-2.5 text-xs text-fg cursor-pointer select-none group ${className}`}
    >
      <div
        className={`flex size-4 shrink-0 items-center justify-center rounded border transition-all duration-150 ${
          checked
            ? 'border-brand bg-brand text-brandfg shadow-2xs'
            : 'border-line bg-panel2 group-hover:border-brand/50'
        }`}
      >
        {checked && <Check className="size-3 stroke-[3]" />}
      </div>
      {label && <span className="font-medium text-fg">{label}</span>}
      {description && <span className="text-muted">{description}</span>}
    </label>
  )
}
