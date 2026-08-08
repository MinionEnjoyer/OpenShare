export function Spinner({ size = 'xs', label = 'Working' }: { size?: 'xs' | 'sm' | 'md'; label?: string }) {
  return <span className={`oc-spinner oc-spinner--${size}`} role="status" aria-label={label} />;
}
