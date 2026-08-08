import type { CSSProperties } from 'react';
import type { Folder, LibraryItem } from './types';

export type PublicFolderData = {
  folder: Folder;
  subfolders: Folder[];
  items: LibraryItem[];
};

export function PublicFolder({ data }: { data: PublicFolderData }) {
  return <section className="os-public-folder" aria-label={`Shared folder ${data.folder.name}`}>
    <header className="public-header"><span className="eyebrow">Shared folder</span><h1>{data.folder.name}</h1><p className="muted">Browse this collection without signing in.</p></header>
    {data.subfolders.length > 0 && <section><h2 className="section-h">Folders</h2><div className="folder-grid">{data.subfolders.map((folder) => <a className="folder-tile" style={{ '--folder-color': folder.color } as CSSProperties} href={`/f/${encodeURIComponent(folder.id)}`} key={folder.id}><span className="folder-icon" aria-hidden="true">{folder.icon}</span><span className="folder-name">{folder.name}</span></a>)}</div></section>}
    {data.items.length > 0 && <section><h2 className="section-h">Files</h2><div className="grid">{data.items.map((item) => <article className="tile-wrap" key={item.id}><a className="tile" href={item.viewUrl} title={item.name}>{item.thumbUrl ? <img src={item.thumbUrl} alt="" loading="lazy" /> : <span className="thumb-missing model-thumb"><span className="model-cube">{item.mediaType === 'audio' ? '♪' : item.extension || item.mediaType}</span></span>}</a><div className="tile-caption" title={item.name}>{item.name}</div></article>)}</div></section>}
    {!data.subfolders.length && !data.items.length && <div className="os-search-empty"><strong>This folder is empty</strong><span>There are no shared files here yet.</span></div>}
  </section>;
}
