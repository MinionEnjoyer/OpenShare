import { CSSProperties, PointerEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Spinner } from './Spinner';
import type { MediaViewerData } from './types';

const clampZoom = (value: number) => Math.max(0.1, Math.min(8, value));
const formatTime = (seconds: number) => {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
};

function ImageSurface({ data }: { data: MediaViewerData }) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState<number | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [attempt, setAttempt] = useState(0);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);

  useEffect(() => {
    const measure = () => setStageSize({
      width: stageRef.current?.clientWidth ?? 0,
      height: stageRef.current?.clientHeight ?? 0,
    });
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, []);

  const fitZoom = useMemo(() => {
    if (!dimensions.width || !dimensions.height || !stageSize.width || !stageSize.height) return 1;
    return Math.min((stageSize.width - 48) / dimensions.width, (stageSize.height - 48) / dimensions.height, 1);
  }, [dimensions, stageSize]);
  const effectiveZoom = zoom ?? fitZoom;
  const displayWidth = Math.max(1, dimensions.width * effectiveZoom);
  const displayHeight = Math.max(1, dimensions.height * effectiveZoom);
  const setZoomAroundCenter = (next: number | null) => {
    setZoom(next === null ? null : clampZoom(next));
    window.requestAnimationFrame(() => {
      const stage = stageRef.current;
      if (!stage) return;
      stage.scrollLeft = Math.max(0, (stage.scrollWidth - stage.clientWidth) / 2);
      stage.scrollTop = Math.max(0, (stage.scrollHeight - stage.clientHeight) / 2);
    });
  };
  const pointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const stage = stageRef.current;
    if (!stage || stage.scrollWidth <= stage.clientWidth && stage.scrollHeight <= stage.clientHeight) return;
    stage.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, left: stage.scrollLeft, top: stage.scrollTop };
  };
  const pointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const stage = stageRef.current;
    if (!stage || !drag.current) return;
    stage.scrollLeft = drag.current.left - (event.clientX - drag.current.x);
    stage.scrollTop = drag.current.top - (event.clientY - drag.current.y);
  };

  return <>
    <div className="os-image-controls" aria-label="Image zoom controls">
      <button type="button" onClick={() => setZoomAroundCenter(clampZoom(effectiveZoom - .25))} aria-label="Zoom out">−</button>
      <button type="button" onClick={() => setZoomAroundCenter(null)} aria-pressed={zoom === null}>Fit</button>
      <button type="button" onClick={() => setZoomAroundCenter(1)} aria-pressed={zoom === 1}>100%</button>
      <button type="button" onClick={() => setZoomAroundCenter(clampZoom(effectiveZoom + .25))} aria-label="Zoom in">+</button>
      <output aria-live="polite">{Math.round(effectiveZoom * 100)}%</output>
    </div>
    <div
      ref={stageRef}
      className={`os-image-stage ${drag.current ? 'is-dragging' : ''}`}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={() => { drag.current = null; }}
      onPointerCancel={() => { drag.current = null; }}
      onWheel={(event) => {
        if (!event.ctrlKey && !event.metaKey) return;
        event.preventDefault();
        setZoomAroundCenter(clampZoom(effectiveZoom + (event.deltaY < 0 ? .15 : -.15)));
      }}
      onDoubleClick={() => setZoomAroundCenter(zoom === 1 ? null : 1)}
    >
      {status === 'loading' && <div className="os-viewer-status"><Spinner size="md" label="Loading image" /><span>Loading image…</span></div>}
      {status === 'error' && <div className="os-viewer-error" role="alert"><strong>Could not load this image</strong><span>The original file may be unavailable or use an unsupported format.</span><button type="button" onClick={() => { setStatus('loading'); setAttempt((value) => value + 1); }}>Try again</button></div>}
      <div className="os-image-canvas" style={{ '--image-width': `${displayWidth}px`, '--image-height': `${displayHeight}px` } as CSSProperties}>
        <img
          key={attempt}
          src={`${data.rawUrl}${attempt ? `?retry=${attempt}` : ''}`}
          alt={data.name}
          draggable={false}
          hidden={status !== 'ready'}
          style={{ width: displayWidth, height: displayHeight }}
          onLoad={(event) => {
            setDimensions({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight });
            setStatus('ready');
          }}
          onError={() => setStatus('error')}
        />
      </div>
    </div>
  </>;
}

function AudioSurface({ data }: { data: MediaViewerData }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [peaks, setPeaks] = useState<number[]>([]);
  const [duration, setDuration] = useState(0);
  const [current, setCurrent] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!data.waveformUrl) return;
    fetch(data.waveformUrl).then((response) => response.ok ? response.json() : null).then((body) => {
      if (Array.isArray(body?.peaks)) setPeaks(body.peaks);
      if (typeof body?.duration === 'number') setDuration(body.duration);
    }).catch(() => undefined);
  }, [data.waveformUrl]);
  return <div className="os-audio-surface">
    <div className="os-audio-art" aria-hidden="true">♪</div>
    <div className="os-audio-player">
      <button className="os-audio-play" type="button" aria-label={playing ? 'Pause' : 'Play'} onClick={() => {
        const audio = audioRef.current;
        if (!audio) return;
        if (audio.paused) void audio.play(); else audio.pause();
      }}>{playing ? 'Ⅱ' : '▶'}</button>
      <button className="os-waveform" type="button" aria-label="Seek audio" onClick={(event) => {
        const audio = audioRef.current;
        if (!audio?.duration) return;
        const rect = event.currentTarget.getBoundingClientRect();
        audio.currentTime = ((event.clientX - rect.left) / rect.width) * audio.duration;
      }}>
        {(peaks.length ? peaks : Array.from({ length: 48 }, (_, index) => 24 + (index % 7) * 7)).map((peak, index) => <span key={index} className={index / Math.max(1, peaks.length) <= current / Math.max(1, duration) ? 'is-played' : ''} style={{ height: `${Math.max(8, peak)}%` }} />)}
      </button>
      <span className="os-audio-time">{formatTime(current)} / {formatTime(duration)}</span>
    </div>
    <audio ref={audioRef} src={data.rawUrl} preload="metadata" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)} onTimeUpdate={(event) => setCurrent(event.currentTarget.currentTime)} />
  </div>;
}

function MediaSurface({ data }: { data: MediaViewerData }) {
  if (data.mediaType === 'image') return <ImageSurface data={data} />;
  if (data.mediaType === 'video') return <video className="os-video-surface" controls preload="metadata" poster={data.thumbUrl ?? undefined} src={data.rawUrl}>Your browser cannot play this video.</video>;
  if (data.mediaType === 'audio') return <AudioSurface data={data} />;
  if (data.mediaType === 'pdf') return <object className="os-pdf-surface" data={data.rawUrl} type="application/pdf"><a href={data.rawUrl}>Open PDF</a></object>;
  if (data.mediaType === 'text') return <div className="os-text-surface"><header>{data.textLanguage ?? 'text'}{data.textTruncated && <span>Preview truncated</span>}</header><pre><code>{data.textBody}</code></pre></div>;
  if (data.mediaType === 'model') return <div id="model-stage" className="os-model-surface" data-src={data.rawUrl} data-ext={data.modelExtension ?? ''} data-mtl={data.modelMaterial ?? undefined}><div className="os-viewer-status"><Spinner size="md" label="Loading 3D model" /><span>Loading {data.modelExtension?.toUpperCase()} model…</span></div></div>;
  return <div className="os-archive-surface"><span aria-hidden="true">▣</span><strong>{data.name}</strong><small>{data.sizeLabel} archive</small><a href={data.rawUrl} download={data.name}>Download to open</a></div>;
}

export function MediaViewer({ data }: { data: MediaViewerData }) {
  const [notice, setNotice] = useState('');
  const [sharing, setSharing] = useState(false);
  useEffect(() => {
    if (data.mediaType === 'model') document.dispatchEvent(new CustomEvent('openshare:model-ready'));
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') window.location.assign(data.backUrl);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [data.backUrl, data.mediaType]);
  const share = async () => {
    setSharing(true); setNotice('');
    try {
      const response = await fetch(data.shareUrl, { method: 'POST', credentials: 'same-origin' });
      if (!response.ok) throw new Error(`Share failed (${response.status})`);
      const result = await response.json() as { url: string };
      if (navigator.share) await navigator.share({ title: data.name, url: result.url });
      else await navigator.clipboard.writeText(result.url);
      setNotice('Share link created and saved');
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : 'Could not create share link');
    } finally { setSharing(false); }
  };
  return <section className="os-media-viewer-root" aria-label={`${data.mediaType} viewer`}>
    <article className="os-media-viewer">
      <header className="os-media-header">
        <a className="os-viewer-back" href={data.backUrl} aria-label="Back to library">←</a>
        <div><span className="eyebrow">{data.mediaType} viewer</span><h1 title={data.name}>{data.name}</h1><p>{data.sizeLabel} · shared by {data.ownerUsername}</p></div>
        <div className="os-viewer-actions">
          {data.canManage && <button type="button" onClick={share} disabled={sharing}>{sharing ? 'Sharing…' : 'Share'}</button>}
          <a href={data.rawUrl} target="_blank" rel="noopener">Open original</a>
          <a href={data.rawUrl} download={data.name}>Download</a>
        </div>
      </header>
      <div className={`os-media-stage is-${data.mediaType}`}><MediaSurface data={data} /></div>
      <footer className="os-media-footer">
        <span>{notice || 'Escape returns to the library'}</span>
        {data.canManage && <form action={data.deleteUrl} method="post" onSubmit={(event) => { if (!window.confirm(`Delete ${data.name}?`)) event.preventDefault(); }}><button className="danger" type="submit">Delete</button></form>}
        <strong>OpenShare v{data.appVersion}</strong>
      </footer>
    </article>
  </section>;
}
