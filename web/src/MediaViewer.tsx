import { CSSProperties, PointerEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Spinner } from './Spinner';
import type { MediaViewerData } from './types';

const clampZoom = (value: number) => Math.max(0.1, Math.min(8, value));
const formatTime = (seconds: number) => {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
};
const browserNavigate = (url: string) => window.location.assign(url);
const acceptsDirectionalInput = (target: EventTarget | null) => {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT', 'AUDIO', 'VIDEO'].includes(target.tagName);
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

type SpreadsheetPreview = {
  sheetNames: string[];
  activeSheet: string | null;
  rows: Array<Array<string | number | boolean | null>>;
  offset: number;
  limit: number;
  totalRows: number;
  totalColumns: number;
  columnsTruncated: boolean;
};

const columnLabel = (index: number) => {
  let label = '';
  for (let value = index + 1; value > 0; value = Math.floor((value - 1) / 26)) label = String.fromCharCode(65 + (value - 1) % 26) + label;
  return label;
};

function SpreadsheetSurface({ data }: { data: MediaViewerData }) {
  const [preview, setPreview] = useState<SpreadsheetPreview | null>(null);
  const [sheet, setSheet] = useState('');
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState('');
  const pageSize = 100;
  useEffect(() => {
    if (!data.spreadsheetUrl) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ offset: String(offset), limit: String(pageSize) });
    if (sheet) params.set('sheet', sheet);
    setPreview(null); setError('');
    fetch(`${data.spreadsheetUrl}?${params}`, { signal: controller.signal })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || `Preview failed (${response.status})`);
        return body as SpreadsheetPreview;
      })
      .then((body) => {
        setPreview({ ...body, sheetNames: body.sheetNames ?? [], rows: body.rows ?? [] });
        if (!sheet && body.activeSheet) setSheet(body.activeSheet);
      })
      .catch((reason) => { if (reason.name !== 'AbortError') setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => controller.abort();
  }, [data.spreadsheetUrl, offset, sheet]);
  const shownColumns = Math.min(preview?.totalColumns ?? 0, 100);
  return <div className="os-spreadsheet-surface">
    {preview && <header className="os-sheet-toolbar"><div className="os-sheet-tabs" role="tablist" aria-label="Workbook sheets">{preview.sheetNames.map((name) => <button type="button" role="tab" aria-selected={preview.activeSheet === name} key={name} onClick={() => { setSheet(name); setOffset(0); }}>{name}</button>)}</div><span>{preview.totalRows.toLocaleString()} rows · {preview.totalColumns.toLocaleString()} columns{preview.columnsTruncated ? ' · showing first 100 columns' : ''}</span></header>}
    {!preview && !error && <div className="os-viewer-status"><Spinner size="md" label="Loading spreadsheet" /><span>Reading workbook…</span></div>}
    {error && <div className="os-viewer-error" role="alert"><strong>Could not preview this spreadsheet</strong><span>{error}</span><a href={data.rawUrl}>Download the original</a></div>}
    {preview && <div className="os-sheet-grid-wrap"><table className="os-sheet-grid"><thead><tr><th className="os-sheet-corner" />{Array.from({ length: shownColumns }, (_, index) => <th key={index} scope="col">{columnLabel(index)}</th>)}</tr></thead><tbody>{preview.rows.map((row, rowIndex) => <tr key={offset + rowIndex}><th scope="row">{offset + rowIndex + 1}</th>{Array.from({ length: shownColumns }, (_, columnIndex) => <td key={columnIndex} title={row[columnIndex] == null ? '' : String(row[columnIndex])}>{row[columnIndex] == null ? '' : String(row[columnIndex])}</td>)}</tr>)}</tbody></table>{preview.totalRows === 0 && <div className="os-sheet-empty">This sheet is empty.</div>}</div>}
    {preview && preview.totalRows > pageSize && <footer className="os-sheet-pager"><button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous rows</button><span>{offset + 1}–{Math.min(offset + preview.rows.length, preview.totalRows)} of {preview.totalRows}</span><button type="button" disabled={offset + pageSize >= preview.totalRows} onClick={() => setOffset(offset + pageSize)}>Next rows</button></footer>}
  </div>;
}

function MediaSurface({ data }: { data: MediaViewerData }) {
  if (data.mediaType === 'image') return <ImageSurface data={data} />;
  if (data.mediaType === 'video') return <video className="os-video-surface" controls preload="metadata" poster={data.thumbUrl ?? undefined} src={data.rawUrl}>Your browser cannot play this video.</video>;
  if (data.mediaType === 'audio') return <AudioSurface data={data} />;
  if (data.mediaType === 'pdf') return <object className="os-pdf-surface" data={data.rawUrl} type="application/pdf"><a href={data.rawUrl}>Open PDF</a></object>;
  if (data.mediaType === 'spreadsheet') return <SpreadsheetSurface data={data} />;
  if (data.mediaType === 'text') return <div className="os-text-surface"><header>{data.textLanguage ?? 'text'}{data.textTruncated && <span>Preview truncated</span>}</header><pre><code>{data.textBody}</code></pre></div>;
  if (data.mediaType === 'model') return <div id="model-stage" className="os-model-surface" data-src={data.rawUrl} data-ext={data.modelExtension ?? ''} data-mtl={data.modelMaterial ?? undefined}><div className="os-viewer-status"><Spinner size="md" label="Loading 3D model" /><span>Loading {data.modelExtension?.toUpperCase()} model…</span></div></div>;
  return <div className="os-archive-surface"><span aria-hidden="true">▣</span><strong>{data.name}</strong><small>{data.sizeLabel} archive</small><a href={data.rawUrl} download={data.name}>Download to open</a></div>;
}

export function MediaViewer({ data, navigate = browserNavigate }: { data: MediaViewerData; navigate?: (url: string) => void }) {
  const [notice, setNotice] = useState('');
  const [sharing, setSharing] = useState(false);
  useEffect(() => {
    if (data.mediaType === 'model') document.dispatchEvent(new CustomEvent('openshare:model-ready'));
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') window.location.assign(data.backUrl);
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || acceptsDirectionalInput(event.target)) return;
      const destination = event.key === 'ArrowLeft' ? data.navigation?.previous : event.key === 'ArrowRight' ? data.navigation?.next : null;
      if (destination) {
        event.preventDefault();
        navigate(destination.viewUrl);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [data.backUrl, data.mediaType, data.navigation, navigate]);
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
      <div className={`os-media-stage is-${data.mediaType}`}>
        <MediaSurface data={data} />
        {data.navigation && data.navigation.total > 1 && <nav className="os-media-pager" aria-label="Files in this folder">
          {data.navigation.previous && <a className="os-media-skip is-previous" href={data.navigation.previous.viewUrl} aria-label={`Previous file: ${data.navigation.previous.name}`} title={`${data.navigation.previous.name} (Left arrow)`}><span aria-hidden="true">‹</span><small>Previous</small></a>}
          {data.navigation.next && <a className="os-media-skip is-next" href={data.navigation.next.viewUrl} aria-label={`Next file: ${data.navigation.next.name}`} title={`${data.navigation.next.name} (Right arrow)`}><small>Next</small><span aria-hidden="true">›</span></a>}
        </nav>}
      </div>
      <footer className="os-media-footer">
        <span>{notice || (data.navigation && data.navigation.total > 1 ? `${data.navigation.position} of ${data.navigation.total} · Use ← → to browse · Escape returns` : 'Escape returns to the library')}</span>
        {data.canManage && <form action={data.deleteUrl} method="post" onSubmit={(event) => { if (!window.confirm(`Delete ${data.name}?`)) event.preventDefault(); }}><button className="danger" type="submit">Delete</button></form>}
        <strong>OpenShare v{data.appVersion}</strong>
      </footer>
    </article>
  </section>;
}
