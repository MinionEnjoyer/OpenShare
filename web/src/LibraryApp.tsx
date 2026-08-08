import { ChangeEvent, CSSProperties, DragEvent, MouseEvent, useRef, useState } from 'react';
import { FolderWorkspace } from './FolderWorkspace';
import { Spinner } from './Spinner';
import type { LibraryData, LibraryItem } from './types';

const uploadAccept = 'image/*,video/*,audio/*,text/*,application/pdf,application/json,application/xml,.stl,.obj,.fbx,.3mf,.step,.stp,.mtl,.zip,.rar,.7z,.tar,.gz,.tgz,.bz2,.xz,.txt,.md,.json,.yaml,.yml,.toml,.ini,.cfg,.csv,.tsv,.xml,.html,.css,.sh,.py,.js,.ts,.go,.rs,.java,.c,.h,.cpp,.hpp,.sql,.log';

function itemGlyph(item: LibraryItem) {
  if (item.mediaType === 'audio') return '♪';
  if (item.mediaType === 'archive') return '▣';
  if (item.mediaType === 'model') return '◇';
  if (item.mediaType === 'pdf') return 'PDF';
  if (item.mediaType === 'text') return item.extension || 'TXT';
  return item.mediaType;
}

export function LibraryApp({ data }: { data: LibraryData }) {
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState('');
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [moving, setMoving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = async (files: FileList | File[]) => {
    if (!files.length || uploading) return;
    setUploading(true); setError(''); setProgress(`Uploading and processing ${files.length} ${files.length === 1 ? 'file' : 'files'}…`);
    const body = new FormData();
    [...files].forEach((file) => body.append('files', file));
    if (data.currentFolder) body.set('folder_id', data.currentFolder.id);
    try {
      const response = await fetch('/upload', { method: 'POST', body, credentials: 'same-origin' });
      const result = await response.json().catch(() => ({})) as { saved?: unknown[]; rejected?: Array<{ name: string; reason: string }> };
      if (!response.ok) throw new Error((result as { detail?: string }).detail || `Upload failed (${response.status})`);
      const saved = result.saved?.length ?? 0;
      if (result.rejected?.length) {
        setError(`Uploaded ${saved}. Skipped ${result.rejected.length}: ${result.rejected.map((entry) => `${entry.name} (${entry.reason})`).join(', ')}`);
      }
      if (saved) {
        setProgress(`Uploaded ${saved}. Refreshing…`);
        window.setTimeout(() => window.location.reload(), 450);
      } else {
        setProgress(''); setUploading(false);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setProgress(''); setUploading(false);
    } finally {
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const toggle = (id: string) => setSelected((before) => {
    const next = new Set(before);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const openItem = (event: MouseEvent, item: LibraryItem) => {
    if (event.metaKey || event.ctrlKey || selected.size) {
      event.preventDefault(); toggle(item.id);
    }
  };
  const bulkMove = async (folderId: string | null) => {
    setMoving(true); setError('');
    try {
      const response = await fetch('/bulk/move', {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [...selected], folder_id: folderId }),
      });
      if (!response.ok) throw new Error(`Move failed (${response.status})`);
      window.location.reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setMoving(false); }
  };
  const bulkDelete = async () => {
    if (!window.confirm(`Delete ${selected.size} selected ${selected.size === 1 ? 'item' : 'items'}?`)) return;
    setMoving(true); setError('');
    try {
      const response = await fetch('/bulk/delete', {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [...selected] }),
      });
      if (!response.ok) throw new Error(`Delete failed (${response.status})`);
      window.location.reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setMoving(false); }
  };

  return <>
    <nav className="crumbs" aria-label="Current location">
      <a href="/" className={`crumb ${!data.currentFolder ? 'current' : ''}`}>All</a>
      {data.breadcrumb.map((folder) => <span key={folder.id} className="os-crumb-part"><span className="crumb-sep">/</span><a href={`/folder/${encodeURIComponent(folder.id)}`} className={`crumb ${folder.id === data.currentFolder?.id ? 'current' : ''}`}>{folder.name}</a></span>)}
    </nav>
    {data.currentFolder && <section className="active-folder" style={{ '--folder-color': data.currentFolder.color } as CSSProperties} aria-label={`Current folder ${data.currentFolder.name}`}>
      <span className="active-folder-orbit" aria-hidden="true"><span>{data.currentFolder.icon}</span></span>
      <div><span className="eyebrow">Current folder</span><h1>{data.currentFolder.name}</h1></div>
    </section>}
    <section
      className={`upload-zone ${dragging ? 'dragover' : ''} ${uploading ? 'busy' : ''}`}
      onDragEnter={(event: DragEvent) => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); setDragging(true); } }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => { if (event.currentTarget === event.target) setDragging(false); }}
      onDrop={(event) => { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files); }}
    >
      <div className="upload-main"><div className="upload-icon" aria-hidden="true">↑</div><div className="upload-prompt"><strong>Drop files here</strong><span className="muted">or</span><label className="btn primary"><input ref={inputRef} type="file" multiple hidden accept={uploadAccept} disabled={uploading} onChange={(event: ChangeEvent<HTMLInputElement>) => { if (event.target.files) void upload(event.target.files); }} />Choose files</label></div><div className="upload-target muted">→ {data.currentFolder?.name ?? 'root'}</div></div>
      {progress && <div className="progress muted" role="status"><Spinner size="sm" label="Uploading files" /> {progress}</div>}
      {error && <div className="progress error" role="alert">{error}</div>}
    </section>
    <FolderWorkspace data={data} />
    {data.items.length > 0 && <section className="grid" aria-label="Files">
      {data.items.map((item) => <article className={`tile-wrap ${selected.has(item.id) ? 'selected' : ''}`} key={item.id}>
        <a className="tile" href={item.viewUrl} title={item.name} onClick={(event) => openItem(event, item)}>
          {item.thumbUrl ? <img src={item.thumbUrl} alt="" loading="lazy" /> : <span className="thumb-missing model-thumb"><span className="model-cube">{itemGlyph(item)}</span>{item.extension && <span className="model-ext">{item.extension}</span>}</span>}
        </a>
        <button className="select-check" type="button" aria-label={`${selected.has(item.id) ? 'Deselect' : 'Select'} ${item.name}`} aria-pressed={selected.has(item.id)} onClick={() => toggle(item.id)} />
        <div className="tile-caption" title={item.name}>{item.name}</div>
      </article>)}
    </section>}
    {!data.items.length && !data.subfolders.length && <p className="empty muted">Nothing here yet. Upload or create a folder above.</p>}
    {selected.size > 0 && <aside className="selection-bar" aria-label="Selected file actions">
      <span className="sel-count">{selected.size} selected</span>
      <label className="os-bulk-destination"><span className="sr-only">Move destination</span><select disabled={moving} defaultValue="__choose__" onChange={(event) => { if (event.target.value !== '__choose__') void bulkMove(event.target.value || null); }}><option value="__choose__">Move to…</option><option value="">Library root</option>{data.allFolders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label>
      <button className="btn danger" type="button" disabled={moving} onClick={bulkDelete}>Delete</button>
      <button className="btn" type="button" disabled={moving} onClick={() => setSelected(new Set())}>Clear</button>
    </aside>}
  </>;
}
