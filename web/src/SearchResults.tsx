import type { CSSProperties } from 'react';
import type { Folder, LibraryItem } from './types';

export type SearchResultsData = {
  query: string;
  folders: Folder[];
  items: LibraryItem[];
};

export function SearchResults({ data }: { data: SearchResultsData }) {
  const total = data.folders.length + data.items.length;
  return <section className="os-search-results" aria-label="Library search results">
    <header className="search-header">
      <span className="eyebrow">Library search</span>
      <h1>{data.query ? `Results for “${data.query}”` : 'Search your library'}</h1>
      {data.query && <p className="muted">{total} {total === 1 ? 'match' : 'matches'} across {data.folders.length} {data.folders.length === 1 ? 'folder' : 'folders'} and {data.items.length} {data.items.length === 1 ? 'file' : 'files'}</p>}
    </header>
    {!data.query && <div className="os-search-empty"><strong>Start with a filename, folder, or file type</strong><span>The search bar will suggest keywords from your library.</span></div>}
    {data.query && !total && <div className="os-search-empty"><strong>No matches</strong><span>Try a shorter keyword or one of the suggestions in the search bar.</span></div>}
    {data.folders.length > 0 && <section><h2 className="section-h">Folders</h2><div className="folder-grid">{data.folders.map((folder) => <a className="folder-tile" style={{ '--folder-color': folder.color } as CSSProperties} href={`/folder/${encodeURIComponent(folder.id)}`} key={folder.id}><span className="folder-icon" aria-hidden="true">{folder.icon}</span><span className="folder-name">{folder.name}</span></a>)}</div></section>}
    {data.items.length > 0 && <section><h2 className="section-h">Files</h2><div className="grid">{data.items.map((item) => <article className="tile-wrap" key={item.id}><a className="tile" href={item.viewUrl} title={item.name}>{item.thumbUrl ? <img src={item.thumbUrl} alt="" loading="lazy" /> : <span className="thumb-missing model-thumb"><span className="model-cube">{item.mediaType === 'audio' ? '♪' : item.extension || item.mediaType}</span></span>}</a><div className="tile-caption" title={item.name}>{item.name}</div></article>)}</div></section>}
  </section>;
}
