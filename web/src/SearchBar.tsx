import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react';

type SearchSuggestion = {
  value: string;
  label: string;
  kind: string;
  count: number;
};

const suggestionCache = new Map<string, SearchSuggestion[]>();

export function SearchBar({ initialQuery = '' }: { initialQuery?: string }) {
  const [query, setQuery] = useState(initialQuery);
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [focused, setFocused] = useState(false);
  const requestRef = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!focused) return;
    const request = ++requestRef.current;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      const key = query.trim().toLocaleLowerCase();
      const cached = suggestionCache.get(key);
      if (cached) {
        setSuggestions(cached);
        setActive(-1);
        setOpen(cached.length > 0);
        return;
      }
      try {
        const response = await fetch(`/api/search/suggestions?q=${encodeURIComponent(query.trim())}`, {
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
        setOpen(next.length > 0);
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        if (request === requestRef.current) {
          setSuggestions([]);
          setOpen(false);
        }
      }
    }, query ? 120 : 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [focused, query]);

  const select = (suggestion: SearchSuggestion) => {
    setQuery(suggestion.value);
    setOpen(false);
    window.location.assign(`/search?q=${encodeURIComponent(suggestion.value)}`);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && open && suggestions.length) {
      event.preventDefault();
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      setActive((before) => (before + direction + suggestions.length) % suggestions.length);
    } else if (event.key === 'Enter' && active >= 0 && suggestions[active]) {
      event.preventDefault();
      select(suggestions[active]);
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

  return <form action="/search" method="get" className="search-bar" role="search" onSubmit={submit}>
    <div className="search-field">
      <span className="search-field-icon" aria-hidden="true">⌕</span>
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
        onFocus={() => setFocused(true)}
        onBlur={() => { setFocused(false); window.setTimeout(() => setOpen(false), 100); }}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <span className="search-field-hint" aria-hidden="true">Enter</span>
    </div>
    {open && <div id="search-suggestions" className="search-suggestions" role="listbox" aria-label="Suggested search keywords">
      <div className="search-suggestions-heading">{query.trim() ? 'Suggested matches' : 'Suggested keywords'}</div>
      {suggestions.map((suggestion, index) => <button
        id={`search-suggestion-${index}`}
        className={`search-suggestion ${active === index ? 'is-active' : ''}`}
        type="button"
        role="option"
        aria-selected={active === index}
        key={`${suggestion.kind}:${suggestion.value}`}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => select(suggestion)}
      >
        <span className="search-suggestion-label">{suggestion.label}</span>
        <span className="search-suggestion-meta">{suggestion.kind}</span>
      </button>)}
    </div>}
  </form>;
}
