import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LibraryApp } from './LibraryApp';
import { MediaViewer } from './MediaViewer';
import { SearchBar } from './SearchBar';
import type { LibraryData, MediaViewerData } from './types';

const viewerData: MediaViewerData = {
  id: 'image-1', name: 'launch.png', mediaType: 'image', rawUrl: '/raw/image-1',
  thumbUrl: '/thumb/image-1', ownerUsername: 'owner', sizeLabel: '32 KB', appVersion: '0.2.34',
  canManage: true, backUrl: '/', deleteUrl: '/delete/image-1', shareUrl: '/media/image-1/shares',
  waveformUrl: null, textBody: null, textLanguage: null, textTruncated: false,
  modelExtension: null, modelMaterial: null,
};

const libraryData: LibraryData = {
  currentFolder: null,
  subfolders: [{ id: 'design', parent_id: null, name: 'Design', color: '#3298ff', icon: 'D' }],
  allFolders: [{ id: 'design', parent_id: null, name: 'Design', color: '#3298ff', icon: 'D' }],
  breadcrumb: [],
  items: [{ id: 'image-1', name: 'launch.png', mediaType: 'image', thumbUrl: '/thumb/image-1', viewUrl: '/i/image-1', extension: 'PNG' }],
  appVersion: '0.2.34', openChatConnected: false,
};

describe('React application surfaces', () => {
  it('shows owner-scoped search suggestions with keyboard selection state', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      suggestions: [{ value: 'launch', label: 'Launch', kind: 'Keyword', count: 2 }],
    }), { status: 200 }));
    render(<SearchBar />);

    const input = screen.getByRole('combobox', { name: 'Search your library' });
    fireEvent.focus(input);
    const option = await screen.findByRole('option', { name: /Launch/ });
    expect(input).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(option).toHaveAttribute('aria-selected', 'true');
  });

  it('renders image recovery and records shares from the common viewer shell', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ url: 'https://share.example.test/ms/link-1' }), { status: 200 }));
    const { container } = render(<MediaViewer data={viewerData} />);

    const image = container.querySelector('img')!;
    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 1200 });
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 800 });
    fireEvent.load(image);
    expect(screen.getByRole('img', { name: 'launch.png' })).toBeVisible();
    expect(screen.getByText('OpenShare v0.2.34')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Share' }));
    expect(await screen.findByText('Share link created and saved')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/media/image-1/shares', { method: 'POST', credentials: 'same-origin' });
  });

  it('keeps the React upload surface above folders and media', () => {
    render(<LibraryApp data={libraryData} />);
    const upload = screen.getByText('Drop files here').closest('.upload-zone')!;
    const folder = screen.getByRole('link', { name: /Design/ });
    const file = screen.getByRole('link', { name: 'launch.png' });
    expect(upload.compareDocumentPosition(folder) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(folder.compareDocumentPosition(file) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
