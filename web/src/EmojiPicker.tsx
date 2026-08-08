import { useEffect, useRef, useState } from 'react';
import { Spinner } from './Spinner';

export function EmojiPicker({ onSelect, onClose }: { onSelect: (emoji: string) => void; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [module, setModule] = useState<{ Picker: any; data: any } | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([import('@emoji-mart/react'), import('@emoji-mart/data')])
      .then(([react, data]) => { if (!cancelled) setModule({ Picker: react.default, data: data.default }); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="os-layer os-layer-emoji" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div ref={ref} className="os-emoji-dialog" role="dialog" aria-modal="true" aria-label="Choose a folder emoji">
        {module ? (
          <module.Picker
            data={module.data}
            onEmojiSelect={(emoji: { native: string }) => onSelect(emoji.native)}
            theme="dark"
            previewPosition="none"
            skinTonePosition="none"
          />
        ) : (
          <div className="os-emoji-loading"><Spinner size="sm" label="Loading emojis" /> Loading emojis…</div>
        )}
      </div>
    </div>
  );
}
