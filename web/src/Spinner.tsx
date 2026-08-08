import type { CSSProperties } from 'react';

type SpinnerStyle = CSSProperties & {
  '--oc-spinner-size'?: string;
  '--oc-glow-offset'?: string;
  '--oc-glow-radius'?: string;
};

const sizes = { xs: 18, sm: 28, md: 48 } as const;

export function Spinner({ size = 'xs', label = 'Working' }: { size?: keyof typeof sizes; label?: string }) {
  const pixels = sizes[size];
  const style: SpinnerStyle = {
    '--oc-spinner-size': `${pixels}px`,
    '--oc-glow-offset': `${pixels <= 24 ? 0.5 : pixels <= 48 ? 1 : 2}px`,
    '--oc-glow-radius': `${pixels <= 24 ? 4 : pixels <= 48 ? 6 : 10}px`,
  };
  return <span className="oc-spinner" role="status" aria-label={label} style={style} />;
}
