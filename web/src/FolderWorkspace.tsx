import { CSSProperties, FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react';
import { EmojiPicker } from './EmojiPicker';
import { Spinner } from './Spinner';
import { applyTheme, storedTheme, type ThemePreference } from './theme';
import { ancestorIds, buildFolderForest, filterTreeIds, flattenVisibleTree } from './tree';
import type { FlatFolderNode, Folder, FolderWorkspaceData } from './types';

type DialogProps = {
  title: string;
  description?: string;
  className?: string;
  onClose: () => void;
  children: React.ReactNode;
};

type ShareLink = {
  id: string;
  folderId: string;
  folderName: string;
  url: string;
  createdAt: string;
  revokedAt: string | null;
};

type CompanionAsset = {
  id: string;
  name: string;
  mediaType: string;
  viewUrl: string;
  thumbUrl: string | null;
  uploadedAt: string;
  sizeBytes: number;
};

function Dialog({ title, description, className = '', onClose, children }: DialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialogRef.current?.focus();
    const onKey = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div className="os-layer" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div ref={dialogRef} tabIndex={-1} className={`os-dialog ${className}`} role="dialog" aria-modal="true" aria-labelledby="os-dialog-title">
        <header className="os-dialog-header">
          <div>
            <span className="eyebrow">OpenShare library</span>
            <h2 id="os-dialog-title">{title}</h2>
            {description && <p>{description}</p>}
          </div>
          <button className="os-icon-button" type="button" aria-label="Close" onClick={onClose}>×</button>
        </header>
        {children}
      </div>
    </div>
  );
}

function childLabel(folder: FlatFolderNode) {
  const count = folder.children.length;
  return count ? `${count} ${count === 1 ? 'folder' : 'folders'}` : 'Empty folder';
}

function FolderVisual({ folder, className }: { folder: Folder; className: string }) {
  const images = folder.preview_images ?? [];
  const mode = folder.preview_mode ?? 'icon';
  const custom = mode === 'custom' ? images.find((image) => image.id === folder.preview_media_id) : undefined;
  const shown = mode === 'dynamic' ? images.slice(0, 4) : custom ? [custom] : [];
  if (!shown.length) return <span className={className} aria-hidden="true">{folder.icon}</span>;
  return <span className={`${className} os-folder-image-preview ${mode === 'dynamic' ? 'is-dynamic' : ''}`} aria-hidden="true">
    {shown.map((image, index) => <img key={image.id} src={image.thumb_url} alt="" loading="lazy" style={{ '--preview-index': index } as CSSProperties} />)}
  </span>;
}

function TreeBrowser({ folders, currentFolder, onClose }: {
  folders: Folder[];
  currentFolder: Folder | null;
  onClose: () => void;
}) {
  const forest = useMemo(() => buildFolderForest(folders), [folders]);
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const initial = ancestorIds(folders, currentFolder?.id ?? null);
    if (currentFolder?.id) initial.add(currentFolder.id);
    forest.forEach((root) => initial.add(root.id));
    return initial;
  });
  const visibleIds = useMemo(() => filterTreeIds(folders, query), [folders, query]);
  const rows = useMemo(() => flattenVisibleTree(forest, expanded, visibleIds), [forest, expanded, visibleIds]);
  const treeRef = useRef<HTMLDivElement>(null);

  const toggle = (id: string) => setExpanded((before) => {
    const next = new Set(before);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const focusRow = (id: string) => treeRef.current?.querySelector<HTMLElement>(`[data-tree-id="${CSS.escape(id)}"]`)?.focus();
  const onTreeKeyDown = (event: KeyboardEvent<HTMLElement>, row: FlatFolderNode | null, index: number) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      const focusable = [...(treeRef.current?.querySelectorAll<HTMLElement>('[data-tree-id]') ?? [])];
      const activeIndex = focusable.indexOf(event.currentTarget);
      const target = event.key === 'Home' ? 0
        : event.key === 'End' ? focusable.length - 1
          : Math.max(0, Math.min(focusable.length - 1, activeIndex + (event.key === 'ArrowDown' ? 1 : -1)));
      focusable[target]?.focus();
      return;
    }
    if (!row) return;
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      if (row.children.length && !expanded.has(row.id)) toggle(row.id);
      else if (row.children.length) focusRow(row.children[0].id);
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      if (row.children.length && expanded.has(row.id)) toggle(row.id);
      else if (row.parentId) focusRow(row.parentId);
    }
    if (event.key === 'Enter' && index >= 0) window.location.assign(`/folder/${encodeURIComponent(row.id)}`);
  };

  return (
    <Dialog title="Library tree" description="Search or move through every folder without losing your place." className="os-tree-dialog" onClose={onClose}>
      <div className="os-tree-toolbar">
        <label className="os-tree-search">
          <span aria-hidden="true">⌕</span>
          <input autoFocus type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a folder" aria-label="Find a folder" />
          {query && <button type="button" onClick={() => setQuery('')} aria-label="Clear folder search">×</button>}
        </label>
        <div className="os-tree-tools" aria-label="Tree display controls">
          <button type="button" onClick={() => setExpanded(new Set(folders.map((folder) => folder.id)))}>Expand all</button>
          <button type="button" onClick={() => setExpanded(new Set())}>Collapse all</button>
        </div>
      </div>
      <div className="os-tree-summary" aria-live="polite">
        <span>{query ? `${rows.length} matching path${rows.length === 1 ? '' : 's'}` : `${folders.length} folders`}</span>
        <span>Arrow keys navigate</span>
      </div>
      <nav ref={treeRef} className="os-tree" aria-label="Folder directory" role="tree">
        <a
          href="/"
          className={`os-tree-row os-tree-root-row ${currentFolder ? '' : 'is-current'}`}
          data-tree-id="root"
          role="treeitem"
          aria-current={currentFolder ? undefined : 'page'}
          onKeyDown={(event) => onTreeKeyDown(event, null, -1)}
        >
          <span className="os-tree-root-mark" aria-hidden="true">⌂</span>
          <span className="os-tree-copy"><strong>All files</strong><small>Library root</small></span>
          {!currentFolder && <span className="os-tree-current">Current</span>}
        </a>
        {rows.map((row, index) => {
          const isCurrent = row.id === currentFolder?.id;
          const isExpanded = expanded.has(row.id) || Boolean(visibleIds);
          const style = { '--tree-depth': row.depth, '--folder-color': row.color } as CSSProperties;
          return (
            <div key={row.id} className="os-tree-item" role="none" style={style}>
              <div className={`os-tree-row ${isCurrent ? 'is-current' : ''}`} role="treeitem" aria-level={row.depth + 1} aria-expanded={row.children.length ? isExpanded : undefined} aria-current={isCurrent ? 'page' : undefined}>
                {row.children.length ? (
                  <button className="os-tree-disclosure" type="button" aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${row.name}`} onClick={() => toggle(row.id)} tabIndex={-1}>
                    <span className={isExpanded ? 'is-open' : ''}>›</span>
                  </button>
                ) : <span className="os-tree-leaf" aria-hidden="true" />}
                <a
                  href={`/folder/${encodeURIComponent(row.id)}`}
                  className="os-tree-target"
                  data-tree-id={row.id}
                  onKeyDown={(event) => onTreeKeyDown(event, row, index)}
                >
                  <span className="os-tree-folder-icon" aria-hidden="true">{row.icon}</span>
                  <span className="os-tree-copy"><strong>{row.name}</strong><small>{childLabel(row)}</small></span>
                  {isCurrent && <span className="os-tree-current">Current</span>}
                  {!isCurrent && row.children.length > 0 && <span className="os-tree-count">{row.children.length}</span>}
                </a>
              </div>
            </div>
          );
        })}
        {rows.length === 0 && <div className="os-tree-empty"><strong>No folders found</strong><span>Try a shorter or different name.</span></div>}
      </nav>
    </Dialog>
  );
}

function validHex(value: string) {
  return /^#[0-9a-f]{6}$/i.test(value);
}

function rgbChannels(value: string) {
  return validHex(value) ? [1, 3, 5].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16)) : [79, 156, 249];
}

function FolderForm({ folder, currentFolder, onClose }: {
  folder: Folder | null;
  currentFolder: Folder | null;
  onClose: () => void;
}) {
  const [name, setName] = useState(folder?.name ?? '');
  const [color, setColor] = useState(folder?.color ?? '#4f9cf9');
  const [icon, setIcon] = useState(folder?.icon ?? '📁');
  const [previewMode, setPreviewMode] = useState<'icon' | 'dynamic' | 'custom'>(folder?.preview_mode ?? 'icon');
  const [previewMediaId, setPreviewMediaId] = useState(folder?.preview_media_id ?? '');
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [r, g, b] = rgbChannels(color);

  const updateChannel = (index: number, value: string) => {
    const channels = rgbChannels(color);
    channels[index] = Math.max(0, Math.min(255, Number.parseInt(value || '0', 10)));
    setColor(`#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !validHex(color)) return;
    setBusy(true);
    setError('');
    const data = new FormData();
    data.set('name', name.trim());
    data.set('color', color.toLowerCase());
    data.set('icon', icon);
    let action = '/folders';
    if (folder) {
      action = `/folders/${encodeURIComponent(folder.id)}/update`;
      data.set('stay', folder.id === currentFolder?.id ? 'self' : 'parent');
      data.set('preview_mode', previewMode);
      data.set('preview_media_id', previewMode === 'custom' ? previewMediaId : '');
    } else {
      data.set('parent_id', currentFolder?.id ?? '');
    }
    try {
      const response = await fetch(action, { method: 'POST', body: data, credentials: 'same-origin' });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${response.status})`);
      }
      window.location.assign(response.url || (currentFolder ? `/folder/${currentFolder.id}` : '/'));
    } catch (reason) {
      setBusy(false);
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <Dialog
      title={folder ? 'Edit folder' : 'Create a folder'}
      description={folder ? 'Update its name and visual identity.' : `Add it ${currentFolder ? `inside ${currentFolder.name}` : 'at the library root'}.`}
      className="os-folder-dialog"
      onClose={onClose}
    >
      <form className="os-folder-form" onSubmit={submit}>
        <div className="os-folder-preview" style={{ '--folder-color': color } as CSSProperties} aria-hidden="true"><span>{icon}</span></div>
        <div className="os-form-stack">
          <label className="os-field"><span>Folder name</span><input autoFocus value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required /></label>
          <fieldset className="os-appearance-fieldset">
            <legend>Folder color</legend>
            <div className="os-color-row">
              <input type="color" value={validHex(color) ? color : '#4f9cf9'} onChange={(event) => setColor(event.target.value)} aria-label="Choose folder color" />
              <label className="os-field os-hex-field"><span>Hex</span><input value={color} onChange={(event) => setColor(event.target.value)} aria-invalid={!validHex(color)} maxLength={7} /></label>
            </div>
            <div className="os-rgb-row" aria-label="RGB folder color values">
              {[['R', r], ['G', g], ['B', b]].map(([label, value], index) => (
                <label className="os-field" key={label}><span>{label}</span><input type="number" min={0} max={255} value={value} onChange={(event) => updateChannel(index, event.target.value)} /></label>
              ))}
            </div>
          </fieldset>
          <fieldset className="os-appearance-fieldset">
            <legend>Folder emoji</legend>
            <button className="os-emoji-trigger" type="button" onClick={() => setEmojiOpen(true)} aria-haspopup="dialog">
              <span aria-hidden="true">{icon}</span><span><strong>Choose emoji</strong><small>Open the full OpenChat emoji library</small></span><span aria-hidden="true">›</span>
            </button>
          </fieldset>
          {folder && <fieldset className="os-appearance-fieldset os-preview-fieldset">
            <legend>Folder preview</legend>
            <p className="os-field-help">Icon-only is the default. Dynamic previews rotate recent images only after you enable them.</p>
            <div className="os-preview-modes">
              {([
                ['icon', 'Icon only', 'Fast and private by default'],
                ['dynamic', 'Dynamic', 'Rotate recent image thumbnails'],
                ['custom', 'Custom image', 'Pin one image as the cover'],
              ] as const).map(([value, label, detail]) => (
                <label className={previewMode === value ? 'is-selected' : ''} key={value}>
                  <input
                    type="radio"
                    name="preview-mode-ui"
                    value={value}
                    checked={previewMode === value}
                    disabled={value !== 'icon' && !(folder.preview_images?.length)}
                    onChange={() => setPreviewMode(value)}
                  />
                  <span><strong>{label}</strong><small>{detail}</small></span>
                </label>
              ))}
            </div>
            {!(folder.preview_images?.length) && <p className="os-field-help">Upload an image to this folder to enable preview choices.</p>}
            {previewMode === 'custom' && Boolean(folder.preview_images?.length) && <div className="os-preview-picker" role="radiogroup" aria-label="Choose folder preview image">
              {folder.preview_images!.map((image) => <label className={previewMediaId === image.id ? 'is-selected' : ''} key={image.id} title={image.name}>
                <input type="radio" name="preview-image-ui" value={image.id} checked={previewMediaId === image.id} onChange={() => setPreviewMediaId(image.id)} />
                <img src={image.thumb_url} alt={image.name} loading="lazy" />
              </label>)}
            </div>}
          </fieldset>}
          {error && <div className="os-form-error" role="alert">{error}</div>}
        </div>
        <footer className="os-dialog-actions">
          <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="primary" type="submit" disabled={busy || !name.trim() || !validHex(color) || (previewMode === 'custom' && !previewMediaId)}>{busy && <Spinner label="Saving folder" />} {folder ? 'Save changes' : 'Create folder'}</button>
        </footer>
      </form>
      {emojiOpen && <EmojiPicker onClose={() => setEmojiOpen(false)} onSelect={(emoji) => { setIcon(emoji); setEmojiOpen(false); }} />}
    </Dialog>
  );
}

function MoveFolderDialog({ folder, folders, onClose }: { folder: Folder; folders: Folder[]; onClose: () => void }) {
  const [target, setTarget] = useState(folder.parent_id ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    const data = new FormData(); data.set('parent_id', target);
    try {
      const response = await fetch(`/folders/${encodeURIComponent(folder.id)}/move`, { method: 'POST', body: data, credentials: 'same-origin' });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `Request failed (${response.status})`);
      window.location.assign(response.url || `/folder/${folder.id}`);
    } catch (reason) { setBusy(false); setError(reason instanceof Error ? reason.message : String(reason)); }
  };
  return <Dialog title="Move folder" description={`Choose a new parent for ${folder.name}.`} onClose={onClose}>
    <form className="os-simple-form" onSubmit={submit}>
      <label className="os-field"><span>Destination</span><select value={target} onChange={(event) => setTarget(event.target.value)}><option value="">Library root</option>{folders.filter((candidate) => candidate.id !== folder.id).map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}</select></label>
      {error && <div className="os-form-error" role="alert">{error}</div>}
      <footer className="os-dialog-actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy && <Spinner label="Moving folder" />} Move folder</button></footer>
    </form>
  </Dialog>;
}

function ShareLinksDialog({ openChatConnected, onClose }: { openChatConnected: boolean; onClose: () => void }) {
  const [links, setLinks] = useState<ShareLink[] | null>(null);
  const [assets, setAssets] = useState<CompanionAsset[] | null>(null);
  const [tab, setTab] = useState<'links' | 'openchat'>('links');
  const [error, setError] = useState('');
  const load = () => {
    setError('');
    fetch('/api/share-links', { credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Request failed (${response.status})`);
        return response.json();
      })
      .then(setLinks)
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  };
  useEffect(load, []);
  useEffect(() => {
    if (tab !== 'openchat' || assets !== null) return;
    setError('');
    fetch('/api/companion-content?app_name=openchat', { credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Request failed (${response.status})`);
        return response.json();
      })
      .then(setAssets)
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [tab, assets]);
  const revoke = async (id: string) => {
    const response = await fetch(`/shares/${encodeURIComponent(id)}/revoke`, { method: 'POST', credentials: 'same-origin' });
    if (response.ok) load(); else setError(`Could not revoke link (${response.status})`);
  };
  return <Dialog title="Shared and companion content" description="Manage public links and content stored on behalf of connected apps." className="os-share-dialog" onClose={onClose}>
    <div className="os-content-tabs" role="tablist" aria-label="Content collections">
      <button type="button" role="tab" aria-selected={tab === 'links'} onClick={() => setTab('links')}>My shared links</button>
      {openChatConnected && <button type="button" role="tab" aria-selected={tab === 'openchat'} onClick={() => setTab('openchat')}>OpenChat content</button>}
    </div>
    <div className="os-share-list">
      {tab === 'links' && links === null && !error && <div className="os-dialog-loading"><Spinner size="sm" label="Loading shared links" /> Loading shared links…</div>}
      {error && <div className="os-form-error" role="alert">{error}</div>}
      {tab === 'links' && links?.length === 0 && <div className="os-share-empty"><strong>No shared links yet</strong><span>Create one from a folder’s actions.</span></div>}
      {tab === 'links' && links?.map((link) => <article className={`os-share-row ${link.revokedAt ? 'is-revoked' : ''}`} key={link.id}>
        <span className="os-share-mark" aria-hidden="true">↗</span>
        <span className="os-share-copy"><strong>{link.folderName}</strong><small>Created {new Date(link.createdAt).toLocaleString()}</small><code>{link.url}</code></span>
        <span className="os-share-actions">
          {!link.revokedAt && <button type="button" onClick={() => navigator.clipboard.writeText(link.url)}>Copy</button>}
          {!link.revokedAt ? <button className="danger" type="button" onClick={() => revoke(link.id)}>Revoke</button> : <span>Revoked</span>}
        </span>
      </article>)}
      {tab === 'openchat' && assets === null && !error && <div className="os-dialog-loading"><Spinner size="sm" label="Loading OpenChat content" /> Loading OpenChat content…</div>}
      {tab === 'openchat' && assets?.length === 0 && <div className="os-share-empty"><strong>No OpenChat content yet</strong><span>Attachments, stickers, avatars, and soundboard uploads will appear here.</span></div>}
      {tab === 'openchat' && assets?.map((asset) => <a className="os-companion-row" href={asset.viewUrl} key={asset.id}>
        <span className="os-companion-thumb">{asset.thumbUrl ? <img src={asset.thumbUrl} alt="" loading="lazy" /> : <span aria-hidden="true">{asset.mediaType === 'audio' ? '♪' : '□'}</span>}</span>
        <span><strong>{asset.name}</strong><small>{asset.mediaType} · {new Date(asset.uploadedAt).toLocaleString()}</small></span><span aria-hidden="true">›</span>
      </a>)}
    </div>
  </Dialog>;
}

function SettingsDialog({ appVersion, onClose }: { appVersion: string; onClose: () => void }) {
  const [theme, setTheme] = useState<ThemePreference>(() => storedTheme());
  useEffect(() => {
    applyTheme(theme);
    if (theme !== 'system') return;
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => applyTheme('system');
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, [theme]);
  return <Dialog title="Settings" description="Personalize this browser without changing server-wide behavior." className="os-settings-dialog" onClose={onClose}>
    <div className="os-settings-body">
      <section><span className="eyebrow">Appearance</span><h3>Theme</h3><p>Match your system or keep OpenShare in a fixed light or dark theme.</p>
        <div className="os-theme-options" role="radiogroup" aria-label="OpenShare theme">
          {([
            ['system', 'System', 'Follow this device'],
            ['dark', 'Dark', 'Low-light interface'],
            ['light', 'Light', 'Bright interface'],
          ] as const).map(([value, label, detail]) => <label className={theme === value ? 'is-selected' : ''} key={value}>
            <input type="radio" name="theme" value={value} checked={theme === value} onChange={() => setTheme(value)} />
            <span className={`os-theme-swatch is-${value}`} aria-hidden="true" />
            <span><strong>{label}</strong><small>{detail}</small></span>
          </label>)}
        </div>
      </section>
      <footer><span>OpenShare</span><strong>v{appVersion}</strong></footer>
    </div>
  </Dialog>;
}

export function FolderWorkspace({ data }: { data: FolderWorkspaceData }) {
  const { currentFolder, subfolders, allFolders, appVersion, openChatConnected } = data;
  const [treeOpen, setTreeOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editing, setEditing] = useState<Folder | null | undefined>(undefined);
  const [moveOpen, setMoveOpen] = useState(false);
  const [sharesOpen, setSharesOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [notice, setNotice] = useState('');

  const copyShareLink = async () => {
    if (!currentFolder) return;
    try {
      const response = await fetch(`/folders/${encodeURIComponent(currentFolder.id)}/shares`, { method: 'POST', credentials: 'same-origin' });
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      const share = await response.json() as { url: string };
      await navigator.clipboard.writeText(share.url);
      setNotice('New share link copied and saved');
    } catch { setNotice('Could not create the share link'); }
    window.setTimeout(() => setNotice(''), 2200);
  };

  const deleteCurrent = async () => {
    if (!currentFolder || !window.confirm(`Delete ${currentFolder.name}? Its contents will move up one level.`)) return;
    const response = await fetch(`/folders/${encodeURIComponent(currentFolder.id)}/delete`, { method: 'POST', credentials: 'same-origin' });
    if (response.ok) window.location.assign(response.url || '/');
    else setNotice(`Could not delete folder (${response.status})`);
  };

  const parentHref = currentFolder?.parent_id ? `/folder/${encodeURIComponent(currentFolder.parent_id)}` : '/';
  return (
    <section className="os-folder-workspace" aria-label="Folder workspace">
      <div className="os-folder-commandbar">
        <div className="os-command-primary">
          <button type="button" onClick={() => setTreeOpen(true)}><span aria-hidden="true">☷</span> Browse library</button>
          <button type="button" className={editMode ? 'is-active' : ''} aria-pressed={editMode} onClick={() => setEditMode((value) => !value)}><span aria-hidden="true">✎</span> {editMode ? 'Done editing' : 'Edit folders'}</button>
        </div>
        <div className="os-command-secondary">
          <button type="button" onClick={() => setSharesOpen(true)}><span aria-hidden="true">↗</span> Shared links</button>
          <button type="button" onClick={() => setSettingsOpen(true)}><span aria-hidden="true">⚙</span> Settings</button>
          <button className="os-new-folder" type="button" onClick={() => setEditing(null)}><span aria-hidden="true">＋</span> New folder</button>
        </div>
      </div>

      {currentFolder && <div className="os-current-actions">
        <span>Folder actions</span>
        <button type="button" onClick={copyShareLink}>Create share link</button>
        <button type="button" onClick={() => setMoveOpen(true)}>Move</button>
        {editMode && <button type="button" onClick={() => setEditing(currentFolder)}>Edit appearance</button>}
        <button className="danger" type="button" onClick={deleteCurrent}>Delete</button>
      </div>}

      {subfolders.length > 0 && <div className="os-folder-grid">
        {subfolders.map((folder) => <article className="os-folder-card" key={folder.id} style={{ '--folder-color': folder.color } as CSSProperties}>
          <a className="os-folder-tile droptarget" href={`/folder/${encodeURIComponent(folder.id)}`} data-folder-id={folder.id}>
            <FolderVisual folder={folder} className="os-folder-card-icon" />
            <span className="os-folder-card-copy"><strong>{folder.name}</strong><small>Open folder</small></span>
            <span className="os-folder-arrow" aria-hidden="true">›</span>
          </a>
          {editMode && <button className="os-folder-card-edit" type="button" onClick={() => setEditing(folder)} aria-label={`Edit ${folder.name}`}>Edit</button>}
        </article>)}
        {currentFolder && <a className="os-folder-card os-folder-up droptarget" href={parentHref} data-folder-id={currentFolder.parent_id ?? ''}>
          <span className="os-folder-card-icon" aria-hidden="true">↰</span><span className="os-folder-card-copy"><strong>Up one level</strong><small>{currentFolder.parent_id ? 'Parent folder' : 'Library root'}</small></span>
        </a>}
      </div>}

      {treeOpen && <TreeBrowser folders={allFolders} currentFolder={currentFolder} onClose={() => setTreeOpen(false)} />}
      {editing !== undefined && <FolderForm folder={editing} currentFolder={currentFolder} onClose={() => setEditing(undefined)} />}
      {moveOpen && currentFolder && <MoveFolderDialog folder={currentFolder} folders={allFolders} onClose={() => setMoveOpen(false)} />}
      {sharesOpen && <ShareLinksDialog openChatConnected={openChatConnected} onClose={() => setSharesOpen(false)} />}
      {settingsOpen && <SettingsDialog appVersion={appVersion} onClose={() => setSettingsOpen(false)} />}
      {notice && <div className="os-toast" role="status">{notice}</div>}
    </section>
  );
}
