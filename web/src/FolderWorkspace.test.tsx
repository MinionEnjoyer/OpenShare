import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FolderWorkspace } from './FolderWorkspace';
import type { FolderWorkspaceData } from './types';

const design = { id: 'design', parent_id: null, name: 'Design', color: '#3298ff', icon: '🎨' };
const drafts = { id: 'drafts', parent_id: 'design', name: 'Drafts', color: '#18d5ad', icon: '📝' };
const data: FolderWorkspaceData = {
  currentFolder: design,
  subfolders: [drafts],
  allFolders: [design, drafts],
  publicUrl: 'https://share.example.test',
  appVersion: '0.2.31',
  openChatConnected: true,
};

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.themePreference;
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

  it('opens a searchable, hierarchical tree in the shared centered surface', () => {
    render(<FolderWorkspace data={data} />);
    fireEvent.click(screen.getByRole('button', { name: /Browse library/ }));

    const dialog = screen.getByRole('dialog', { name: 'Library tree' });
    expect(dialog).toHaveClass('os-tree-dialog');
    expect(within(dialog).getByRole('tree')).toBeInTheDocument();
    expect(within(dialog).getByRole('treeitem', { name: /Design/ })).toHaveAttribute('aria-current', 'page');

    fireEvent.change(within(dialog).getByRole('searchbox', { name: 'Find a folder' }), { target: { value: 'draft' } });
    expect(within(dialog).getByRole('treeitem', { name: /Drafts/ })).toBeInTheDocument();
    expect(within(dialog).queryByText('No folders found')).not.toBeInTheDocument();
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
    expect(screen.getByText('v0.2.31')).toBeInTheDocument();
  });

  it('keeps connected OpenChat assets beside shared links, not in the folder tree', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{
        id: 'chat-asset', name: 'sticker.png', mediaType: 'image', viewUrl: '/i/chat-asset',
        thumbUrl: '/thumb/chat-asset', uploadedAt: '2026-08-07T08:00:00Z', sizeBytes: 32,
      }]), { status: 200 }));
    render(<FolderWorkspace data={data} />);
    fireEvent.click(screen.getByRole('button', { name: /Shared links/ }));
    fireEvent.click(screen.getByRole('tab', { name: 'OpenChat content' }));

    expect(await screen.findByRole('link', { name: /sticker\.png/ })).toHaveAttribute('href', '/i/chat-asset');
    expect(screen.queryByRole('treeitem', { name: /OpenChat|Chat/ })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith('/api/companion-content?app_name=openchat', { credentials: 'same-origin' });
  });
});
