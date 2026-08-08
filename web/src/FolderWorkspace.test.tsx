import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FolderWorkspace } from './FolderWorkspace';
import type { FolderWorkspaceData } from './types';

const design = { id: 'design', parent_id: null, name: 'Design', color: '#3298ff', icon: '🎨', child_count: 1, item_count: 4 };
const drafts = { id: 'drafts', parent_id: 'design', name: 'Drafts', color: '#18d5ad', icon: '📝', child_count: 0, item_count: 2 };
const media = { id: 'media', parent_id: null, name: 'Media', color: '#9b72ff', icon: '▣', child_count: 0, item_count: 3 };
const data: FolderWorkspaceData = {
  currentFolder: design,
  subfolders: [drafts],
  allFolders: [design, drafts, media],
  appVersion: '0.2.34',
  openChatConnected: true,
};

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.themePreference;
  delete document.documentElement.dataset.folderDensity;
  delete document.documentElement.dataset.motion;
});

describe('React folder workspace', () => {
  it('keeps edit controls hidden until edit mode is selected', () => {
    render(<FolderWorkspace data={data} />);
    expect(screen.queryByRole('button', { name: 'Edit Drafts' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Edit folders/ }));
    expect(screen.getByRole('button', { name: 'Edit Drafts' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit appearance' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Done editing/ }));
    expect(screen.queryByRole('button', { name: 'Edit Drafts' })).not.toBeInTheDocument();
  });

  it('opens a compact Linux-style folder tree in the shared centered surface', () => {
    render(<FolderWorkspace data={data} />);
    fireEvent.click(screen.getByRole('button', { name: /Browse library/ }));

    const dialog = screen.getByRole('dialog', { name: 'Browse library' });
    expect(dialog).toHaveClass('os-tree-dialog');
    expect(within(dialog).queryByRole('complementary')).not.toBeInTheDocument();
    const tree = within(dialog).getByRole('tree', { name: 'Folder directory' });
    expect(within(tree).getByRole('treeitem', { name: /OpenShare/ })).toHaveAttribute('aria-level', '1');
    expect(within(tree).getByRole('treeitem', { name: /Design/ })).toHaveAttribute('aria-current', 'page');
    const nested = within(tree).getByRole('treeitem', { name: /Drafts/ });
    expect(nested).toHaveAttribute('aria-level', '3');
    expect(nested.closest('.os-tree-item')).toHaveAttribute('data-depth', '1');
    expect(nested.closest('.os-tree-item')?.querySelector('.os-tree-guide')).toHaveClass('is-continuing');

    fireEvent.change(within(dialog).getByRole('searchbox', { name: 'Find a folder' }), { target: { value: 'draft' } });
    expect(within(dialog).getByRole('treeitem', { name: /Drafts/ })).toBeInTheDocument();
    expect(within(dialog).getByText('2 matching folders')).toBeInTheDocument();
    expect(within(dialog).queryByText('No folders found')).not.toBeInTheDocument();
  });

  it('collapses, expands, and navigates the visible tree from the keyboard', () => {
    render(<FolderWorkspace data={data} />);
    fireEvent.click(screen.getByRole('button', { name: /Browse library/ }));
    const dialog = screen.getByRole('dialog', { name: 'Browse library' });
    const tree = within(dialog).getByRole('tree', { name: 'Folder directory' });

    fireEvent.click(within(dialog).getByRole('button', { name: 'Collapse' }));
    expect(within(tree).queryByRole('treeitem', { name: /Drafts/ })).not.toBeInTheDocument();
    const designLink = within(tree).getByRole('link', { name: /Design/ });
    fireEvent.keyDown(designLink, { key: 'ArrowRight' });
    expect(within(tree).getByRole('treeitem', { name: /Drafts/ })).toBeInTheDocument();
    fireEvent.keyDown(designLink, { key: 'ArrowRight' });
    expect(within(tree).getByRole('link', { name: /Drafts/ })).toHaveFocus();
  });

  it('opens create and edit forms as centered dialogs with RGB controls', () => {
    render(<FolderWorkspace data={data} />);
    fireEvent.click(screen.getByRole('button', { name: /New folder/ }));
    const create = screen.getByRole('dialog', { name: 'Create a folder' });
    expect(within(create).getByRole('button', { name: /Choose emoji/ })).toBeInTheDocument();
    expect(within(create).getByLabelText('RGB folder color values')).toBeInTheDocument();
  });

  it('offers opt-in dynamic and custom previews when a folder has images', () => {
    const previewData: FolderWorkspaceData = {
      ...data,
      subfolders: [{
        ...drafts,
        preview_mode: 'icon',
        preview_images: [{ id: 'image-1', name: 'Cover', thumb_url: '/thumb/image-1' }],
      }],
    };
    render(<FolderWorkspace data={previewData} />);
    fireEvent.click(screen.getByRole('button', { name: /Edit folders/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit Drafts' }));

    const dialog = screen.getByRole('dialog', { name: 'Edit folder' });
    expect(within(dialog).getByRole('radio', { name: /Dynamic/ })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole('radio', { name: /Custom image/ }));
    expect(within(dialog).getByRole('radiogroup', { name: 'Choose folder preview image' })).toBeInTheDocument();
  });

  it('applies and persists the selected appearance theme', () => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    });
    render(<FolderWorkspace data={data} />);
    fireEvent.click(screen.getByRole('button', { name: /Settings/ }));
    fireEvent.click(screen.getByRole('radio', { name: /Dark/ }));

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(window.localStorage.getItem('openshare-theme')).toBe('dark');
    expect(screen.getByText('OpenShare v0.2.34')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: /Compact/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Reduce animation/ }));
    expect(document.documentElement.dataset.folderDensity).toBe('compact');
    expect(document.documentElement.dataset.motion).toBe('reduced');
    expect(window.localStorage.getItem('openshare-preferences')).toContain('compact');
  });

  it('imports an existing folder link into My shared links', async () => {
    const legacy = {
      id: 'legacy-link', folderId: 'design', folderName: 'Design',
      url: 'https://share.example.test/f/design', createdAt: '2026-08-08T08:00:00Z',
      revokedAt: null, legacy: true,
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(legacy), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([legacy]), { status: 200 }));
    render(<FolderWorkspace data={data} />);
    fireEvent.click(screen.getByRole('button', { name: /Shared links/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Add existing link' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Existing folder link' }), { target: { value: legacy.url } });
    fireEvent.click(screen.getByRole('button', { name: 'Add to list' }));

    expect(await screen.findByText('Existing link')).toBeInTheDocument();
    expect(screen.getByText(legacy.url)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/shares/import', expect.objectContaining({ method: 'POST', credentials: 'same-origin' }));
  });

  it('keeps connected OpenChat assets beside shared links, not in the folder tree', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{
        id: 'chat-asset', name: 'sticker.png', mediaType: 'image', viewUrl: '/i/chat-asset',
        thumbUrl: '/thumb/chat-asset', uploadedAt: '2026-08-07T08:00:00Z', sizeBytes: 32, duplicateCount: 3,
      }]), { status: 200 }));
    render(<FolderWorkspace data={data} />);
    fireEvent.click(screen.getByRole('button', { name: /Shared links/ }));
    fireEvent.click(screen.getByRole('tab', { name: 'OpenChat content' }));

    expect(await screen.findByRole('link', { name: /sticker\.png/ })).toHaveAttribute('href', '/i/chat-asset');
    expect(screen.getByText(/3 identical uploads grouped/)).toBeInTheDocument();
    expect(screen.queryByRole('treeitem', { name: /OpenChat|Chat/ })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith('/api/companion-content?app_name=openchat', { credentials: 'same-origin' });
  });
});
