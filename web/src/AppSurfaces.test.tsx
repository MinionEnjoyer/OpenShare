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
  waveformUrl: null, spreadsheetUrl: null, textBody: null, textLanguage: null, textTruncated: false,
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

  it('renders a paged multi-sheet spreadsheet inside the common viewer shell', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({
      sheetNames: ['Overview', 'Costs'], activeSheet: 'Overview', rows: [['Name', 'Amount'], ['Hosting', 42]],
      offset: 0, limit: 100, totalRows: 2, totalColumns: 2, columnsTruncated: false,
    }), { status: 200 }));
    render(<MediaViewer data={{ ...viewerData, id: 'sheet-1', name: 'budget.xlsx', mediaType: 'spreadsheet', rawUrl: '/raw/sheet-1', spreadsheetUrl: '/api/spreadsheets/sheet-1' }} />);

    expect(await screen.findByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('cell', { name: 'Hosting' })).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
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
    expect(screen.getByRole('button', { name: /Paste text/ })).toBeVisible();
    expect(screen.getByText('Files that have not been organized into a folder yet.')).toBeInTheDocument();
    expect(screen.getByLabelText('Library summary')).toHaveTextContent('1 folder');
    expect(screen.getByLabelText('Library summary')).toHaveTextContent('1 unsorted');
  });

  it('uses the selected folder for picker and drag-and-drop uploads', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ saved: [] }), { status: 200 }));
    fetchMock.mockClear();
    const { container } = render(<LibraryApp data={libraryData} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Upload destination' }), { target: { value: 'design' } });
    expect(screen.getByRole('combobox', { name: 'Upload destination' })).toHaveValue('design');
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(['sample'], 'sample.txt', { type: 'text/plain' })] } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const request = fetchMock.mock.calls.find(([url]) => url === '/upload')?.[1] as RequestInit;
    expect((request.body as FormData).get('folder_id')).toBe('design');
  });

  it('defaults uploads to Unsorted even while viewing a folder', () => {
    render(<LibraryApp data={{ ...libraryData, currentFolder: libraryData.allFolders[0], breadcrumb: [{ id: 'design', name: 'Design' }] }} />);
    expect(screen.getByRole('combobox', { name: 'Upload destination' })).toHaveValue('');
    expect(screen.queryByText(/Destination:/)).not.toBeInTheDocument();
  });

  it('chooses bulk move destinations from the directory browser', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'test stop' }), { status: 500 }));
    render(<LibraryApp data={libraryData} />);
    fireEvent.click(screen.getByRole('button', { name: 'Select launch.png' }));
    fireEvent.click(screen.getByRole('button', { name: 'Move to…' }));

    expect(screen.getByRole('dialog', { name: 'Choose destination' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Design/ }));
    expect(screen.getByText('Move to').parentElement).toHaveTextContent('Design');
    fireEvent.click(screen.getByRole('button', { name: 'Move here' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/bulk/move', expect.objectContaining({ method: 'POST' })));
    const request = fetchMock.mock.calls.find(([url]) => url === '/bulk/move')?.[1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({ ids: ['image-1'], folder_id: 'design' });
  });

  it('uploads clipboard text as a normal file and records a share link', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    fetchMock.mockReset()
      .mockResolvedValueOnce(new Response(JSON.stringify({ saved: [{ id: 'paste-1' }], rejected: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ url: 'https://share.example.test/ms/paste-link' }), { status: 200 }));
    render(<LibraryApp data={libraryData} />);

    fireEvent.click(screen.getByRole('button', { name: /Paste text/ }));
    expect(screen.getByRole('dialog', { name: 'Share clipboard text' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Paste destination' })).toHaveValue('');
    fireEvent.change(screen.getByRole('combobox', { name: 'Paste destination' }), { target: { value: 'design' } });
    fireEvent.change(screen.getByLabelText('File name'), { target: { value: 'release-notes' } });
    fireEvent.change(screen.getByLabelText('Text'), { target: { value: 'Large clipboard text\nwith Unicode: ✓' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save and copy link' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const uploadRequest = fetchMock.mock.calls[0][1] as RequestInit;
    const body = uploadRequest.body as FormData;
    const uploaded = body.get('files') as File;
    expect(uploaded.name).toBe('release-notes.txt');
    const uploadedText = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(uploaded);
    });
    expect(uploadedText).toBe('Large clipboard text\nwith Unicode: ✓');
    expect(body.get('folder_id')).toBe('design');
    expect(fetchMock).toHaveBeenLastCalledWith('/media/paste-1/shares', { method: 'POST', credentials: 'same-origin' });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://share.example.test/ms/paste-link');
    expect(await screen.findByText('Share link created and copied')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'https://share.example.test/ms/paste-link' })).toHaveAttribute('href', 'https://share.example.test/ms/paste-link');
  });

  it('keeps an empty quick paste in the dialog with a clear validation error', () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    fetchMock.mockClear();
    render(<LibraryApp data={libraryData} />);
    fireEvent.click(screen.getByRole('button', { name: /Paste text/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save and copy link' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Paste some text before saving.');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
