export interface CustomRadioProps {
  checked: boolean
  onChange: () => void
  label?: string
  description?: string
  className?: string
}

export function CustomRadio({
  checked,
  onChange,
  label,
  description,
  className = '',
}: CustomRadioProps) {
  return (
    <label
      onClick={onChange}
      className={`flex items-center gap-2.5 text-xs text-fg cursor-pointer select-none group ${className}`}
    >
      <div
        className={`flex size-4 shrink-0 items-center justify-center rounded-full border transition-all duration-150 ${
          checked
            ? 'border-brand bg-panel ring-2 ring-brand/15'
            : 'border-line bg-panel2 group-hover:border-brand/50'
        }`}
      >
        {checked && (
          <div className="size-2 rounded-full bg-brand animate-in zoom-in-75 duration-100" />
        )}
      </div>
      {label && <span className="font-semibold text-fg">{label}</span>}
      {description && <span className="text-muted">{description}</span>}
    </label>
  )
}
