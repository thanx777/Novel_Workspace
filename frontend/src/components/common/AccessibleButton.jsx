/**
 * AccessibleButton — 可访问的点击区域
 * 封装 role="button" + tabIndex + onKeyDown(Enter/Space) + onClick
 */
export function AccessibleButton({ onClick, children, className, disabled, ...rest }) {
  const handleKeyDown = (e) => {
    if (disabled) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onClick?.(e)
    }
  }
  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      onClick={disabled ? undefined : onClick}
      onKeyDown={handleKeyDown}
      className={className}
      aria-disabled={disabled || undefined}
      {...rest}
    >
      {children}
    </div>
  )
}
