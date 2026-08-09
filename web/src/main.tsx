import React from 'react';
import { createRoot } from 'react-dom/client';
import type { SearchResultsData } from './SearchResults';
import type { PublicFolderData } from './PublicFolder';
import type { LibraryData, MediaViewerData } from './types';
import './workspace.css';
import './mediaViewer.css';
import './contactManager.css';
import { applyTheme, storedTheme } from './theme';
import { applyPreferences, storedPreferences } from './preferences';

const root = document.getElementById('folder-workspace');
const source = document.getElementById('folder-workspace-data');

if (root && source?.textContent) {
  applyTheme(storedTheme());
  applyPreferences(storedPreferences());
  const data = JSON.parse(source.textContent) as LibraryData;
  void import('./LibraryApp').then(({ LibraryApp }) => {
    createRoot(root).render(<React.StrictMode><LibraryApp data={data} /></React.StrictMode>);
  });
}

const searchRoot = document.getElementById('global-search');
const searchSource = document.getElementById('global-search-data');
if (searchRoot && searchSource?.textContent) {
  const data = JSON.parse(searchSource.textContent) as { query?: string };
  void import('./SearchBar').then(({ SearchBar }) => {
    createRoot(searchRoot).render(<SearchBar initialQuery={data.query} />);
  });
}

const viewerRoot = document.getElementById('media-viewer-root');
const viewerSource = document.getElementById('media-viewer-data');
if (viewerRoot && viewerSource?.textContent) {
  applyTheme(storedTheme());
  const data = JSON.parse(viewerSource.textContent) as MediaViewerData;
  void import('./MediaViewer').then(({ MediaViewer }) => {
    createRoot(viewerRoot).render(<React.StrictMode><MediaViewer data={data} /></React.StrictMode>);
  });
}

const resultsRoot = document.getElementById('search-results-root');
const resultsSource = document.getElementById('search-results-data');
if (resultsRoot && resultsSource?.textContent) {
  const data = JSON.parse(resultsSource.textContent) as SearchResultsData;
  void import('./SearchResults').then(({ SearchResults }) => {
    createRoot(resultsRoot).render(<React.StrictMode><SearchResults data={data} /></React.StrictMode>);
  });
}

const publicRoot = document.getElementById('public-folder-root');
const publicSource = document.getElementById('public-folder-data');
if (publicRoot && publicSource?.textContent) {
  const data = JSON.parse(publicSource.textContent) as PublicFolderData;
  void import('./PublicFolder').then(({ PublicFolder }) => {
    createRoot(publicRoot).render(<React.StrictMode><PublicFolder data={data} /></React.StrictMode>);
  });
}

const contactsRoot = document.getElementById('contact-manager-root');
const contactsSource = document.getElementById('contact-manager-data');
if (contactsRoot && contactsSource?.textContent) {
  applyTheme(storedTheme());
  const data = JSON.parse(contactsSource.textContent) as { appVersion: string; openChatUrl: string | null };
  void import('./ContactManager').then(({ ContactManager }) => {
    createRoot(contactsRoot).render(<React.StrictMode><ContactManager data={data} /></React.StrictMode>);
  });
}
