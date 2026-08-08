import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react';

type SearchSuggestion = {
  value: string;
  label: string;
  kind: string;
  count: number;
  url?: string;
};

const suggestionCache = new Map<string, SearchSuggestion[]>();

export function SearchBar({ initialQuery = '' }: { initialQuery?: string }) {
  const [query, setQuery] = useState(initialQuery);
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [focused, setFocused] = useState(false);
  const [loading, setLoading] = useState(false);
  const requestRef = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!focused) return;
    const value = query.trim();
    if (value.length < 2) {
      setSuggestions([]);
      setActive(-1);
      setOpen(false);
      setLoading(false);
      return;
    }
    const request = ++requestRef.current;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      const key = value.toLocaleLowerCase();
      const cached = suggestionCache.get(key);
      if (cached) {
        setSuggestions(cached);
        setActive(-1);
        setOpen(true);
        setLoading(false);
        return;
      }
      setLoading(true);
      setOpen(true);
      try {
        const response = await fetch(`/api/search/suggestions?q=${encodeURIComponent(value)}`, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Suggestions failed (${response.status})`);
        const body = await response.json() as { suggestions?: SearchSuggestion[] };
        if (request !== requestRef.current) return;
        const next = Array.isArray(body.suggestions) ? body.suggestions : [];
        suggestionCache.set(key, next);
        setSuggestions(next);
        setActive(-1);
        setOpen(true);
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        if (request === requestRef.current) {
          setSuggestions([]);
          setOpen(true);
        }
      } finally {
        if (request === requestRef.current) setLoading(false);
      }
    }, 150);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [focused, query]);

  const navigate = (value: string, url?: string) => {
    setQuery(value);
    setOpen(false);
    window.location.assign(url ?? `/search?q=${encodeURIComponent(value)}`);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const optionCount = suggestions.length + 1;
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && open && optionCount) {
      event.preventDefault();
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      setActive((before) => (before + direction + optionCount) % optionCount);
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault();
      const suggestion = suggestions[active];
      navigate(suggestion?.value ?? query.trim(), suggestion?.url);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false);
      setActive(-1);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = query.trim();
    if (value) window.location.assign(`/search?q=${encodeURIComponent(value)}`);
  };

  const value = query.trim();

  return <form action="/search" method="get" className="search-bar" role="search" onSubmit={submit}>
    <div className="search-field">
      <span className="search-field-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false"><circle cx="10.8" cy="10.8" r="6.3" /><path d="m15.6 15.6 4.1 4.1" /></svg>
      </span>
      <input
        ref={inputRef}
        type="search"
        name="q"
        placeholder="Search files, folders, or types…"
        value={query}
        autoComplete="off"
        role="combobox"
        aria-label="Search your library"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls="search-suggestions"
        aria-activedescendant={active >= 0 ? `search-suggestion-${active}` : undefined}
        onFocus={() => { setFocused(true); if (query.trim().length >= 2) setOpen(true); }}
        onBlur={() => { setFocused(false); window.setTimeout(() => setOpen(false), 100); }}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={onKeyDown}
      />
      {query && <button className="search-field-clear" type="button" aria-label="Clear search" onMouseDown={(event) => event.preventDefault()} onClick={() => { setQuery(''); setSuggestions([]); setOpen(false); inputRef.current?.focus(); }}>×</button>}
    </div>
    {open && value.length >= 2 && <div id="search-suggestions" className="search-suggestions" role="listbox" aria-label="Live library matches">
      <div className="search-suggestions-heading"><span>Quick results</span><span>{loading ? 'Searching…' : `${suggestions.length} found`}</span></div>
      {!loading && suggestions.length === 0 && <div className="search-suggestions-empty">No direct matches yet. Search the full library instead.</div>}
      {suggestions.map((suggestion, index) => <button
        id={`search-suggestion-${index}`}
        className={`search-suggestion ${active === index ? 'is-active' : ''}`}
        type="button"
        role="option"
        aria-selected={active === index}
        key={`${suggestion.kind}:${suggestion.value}`}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => navigate(suggestion.value, suggestion.url)}
      >
        <span className={`search-suggestion-icon is-${suggestion.kind === 'Folder' ? 'folder' : 'file'}`} aria-hidden="true">{suggestion.kind === 'Folder' ? '/' : '·'}</span>
        <span className="search-suggestion-copy"><span className="search-suggestion-label">{suggestion.label}</span><span className="search-suggestion-meta">{suggestion.kind}</span></span>
        <span className="search-suggestion-open" aria-hidden="true">›</span>
      </button>)}
      <button
        id={`search-suggestion-${suggestions.length}`}
        className={`search-all ${active === suggestions.length ? 'is-active' : ''}`}
        type="button"
        role="option"
        aria-selected={active === suggestions.length}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => navigate(value)}
      ><span>Search all for “{value}”</span><span aria-hidden="true">↵</span></button>
    </div>}
  </form>;
}
