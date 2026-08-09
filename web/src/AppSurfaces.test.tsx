import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LibraryApp } from './LibraryApp';
import { MediaViewer } from './MediaViewer';
import { SearchBar } from './SearchBar';
import type { LibraryData, MediaViewerData } from './types';

const viewerData: MediaViewerData = {
  id: 'image-1', name: 'launch.png', mediaType: 'image', rawUrl: '/raw/image-1',
  thumbUrl: '/thumb/image-1', ownerUsername: 'owner', sizeLabel: '32 KB', appVersion: '0.2.35',
  canManage: true, backUrl: '/', deleteUrl: '/delete/image-1', shareUrl: '/media/image-1/shares',
  waveformUrl: null, textBody: null, textLanguage: null, textTruncated: false,
  modelExtension: null, modelMaterial: null,
  navigation: {
    position: 2, total: 3,
    previous: { id: 'video-1', name: 'intro.mp4', mediaType: 'video', viewUrl: '/v/video-1' },
    next: { id: 'audio-1', name: 'theme.wav', mediaType: 'audio', viewUrl: '/au/audio-1' },
  },
};

const libraryData: LibraryData = {
  currentFolder: null,
  subfolders: [{ id: 'design', parent_id: null, name: 'Design', color: '#3298ff', icon: 'D' }],
  allFolders: [{ id: 'design', parent_id: null, name: 'Design', color: '#3298ff', icon: 'D' }],
  breadcrumb: [],
  items: [{ id: 'image-1', name: 'launch.png', mediaType: 'image', thumbUrl: '/thumb/image-1', viewUrl: '/i/image-1', extension: 'PNG' }],
  appVersion: '0.2.35', openChatConnected: false,
};

describe('React application surfaces', () => {
  it('progressively shows owner-scoped library matches after typing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      suggestions: [{ value: 'launch.png', label: 'launch.png', kind: 'Images', count: 1, url: '/i/image-1' }],
    }), { status: 200 }));
    render(<SearchBar />);

    const input = screen.getByRole('combobox', { name: 'Search your library' });
    fireEvent.focus(input);
    expect(globalThis.fetch).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: 'lau' } });
    const option = await screen.findByRole('option', { name: /launch\.png/ });
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/search/suggestions?q=lau', expect.objectContaining({ credentials: 'same-origin' }));
    expect(screen.getByRole('option', { name: /Search all for “lau”/ })).toBeInTheDocument();
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
    expect(screen.getByRole('link', { name: 'Previous file: intro.mp4' })).toHaveAttribute('href', '/v/video-1');
    expect(screen.getByRole('link', { name: 'Next file: theme.wav' })).toHaveAttribute('href', '/au/audio-1');
    expect(screen.getByText(/2 of 3/)).toBeInTheDocument();
    expect(screen.getByText('OpenShare v0.2.35')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Share' }));
    expect(await screen.findByText('Share link created and saved')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/media/image-1/shares', { method: 'POST', credentials: 'same-origin' });
  });

  it('uses unmodified arrow keys to browse neighboring files', () => {
    const navigate = vi.fn();
    render(<MediaViewer data={viewerData} navigate={navigate} />);
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(navigate).toHaveBeenCalledWith('/au/audio-1');
    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    expect(navigate).toHaveBeenLastCalledWith('/v/video-1');
  });

  it('keeps the React upload surface above folders and media', () => {
    render(<LibraryApp data={libraryData} />);
    const upload = screen.getByText('Drop files here').closest('.upload-zone')!;
    const folder = screen.getByRole('link', { name: /Design/ });
    const file = screen.getByRole('link', { name: 'launch.png' });
    expect(upload.compareDocumentPosition(folder) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(folder.compareDocumentPosition(file) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Folders' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Unsorted files' })).toBeInTheDocument();
    expect(screen.getByText('Files that have not been organized into a folder yet.')).toBeInTheDocument();
    expect(screen.getByLabelText('Library summary')).toHaveTextContent('1 folder');
    expect(screen.getByLabelText('Library summary')).toHaveTextContent('1 unsorted');
  });

  it('uses the selected folder for picker and drag-and-drop uploads', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ saved: [] }), { status: 200 }));
    fetchMock.mockClear();
    const { container } = render(<LibraryApp data={libraryData} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Upload destination' }), { target: { value: 'design' } });
    expect(screen.getByText('Destination: Design')).toBeInTheDocument();
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(['sample'], 'sample.txt', { type: 'text/plain' })] } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const request = fetchMock.mock.calls.find(([url]) => url === '/upload')?.[1] as RequestInit;
    expect((request.body as FormData).get('folder_id')).toBe('design');
  });

  it('defaults uploads to Unsorted even while viewing a folder', () => {
    render(<LibraryApp data={{ ...libraryData, currentFolder: libraryData.allFolders[0], breadcrumb: [{ id: 'design', name: 'Design' }] }} />);
    expect(screen.getByRole('combobox', { name: 'Upload destination' })).toHaveValue('');
    expect(screen.getByText('Destination: Unsorted')).toBeInTheDocument();
  });
});
