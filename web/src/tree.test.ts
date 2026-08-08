import { describe, expect, it } from 'vitest';
import { ancestorIds, buildFolderForest, filterTreeIds, flattenVisibleTree } from './tree';
import type { Folder } from './types';

const folders: Folder[] = [
  { id: 'design', parent_id: null, name: 'Design', color: '#3298ff', icon: '🎨' },
  { id: 'drafts', parent_id: 'design', name: 'Drafts', color: '#18d5ad', icon: '📝' },
  { id: 'archive', parent_id: null, name: 'Archive', color: '#9b72ff', icon: '🗃️' },
];

describe('folder tree model', () => {
  it('sorts roots and preserves nested folders', () => {
    const forest = buildFolderForest(folders);
    expect(forest.map((folder) => folder.id)).toEqual(['archive', 'design']);
    expect(forest[1].children.map((folder) => folder.id)).toEqual(['drafts']);
  });

  it('includes ancestors when filtering a nested match', () => {
    expect([...filterTreeIds(folders, 'draft')!].sort()).toEqual(['design', 'drafts']);
  });

  it('flattens only expanded branches outside search mode', () => {
    const forest = buildFolderForest(folders);
    expect(flattenVisibleTree(forest, new Set()).map((folder) => folder.id)).toEqual(['archive', 'design']);
    expect(flattenVisibleTree(forest, new Set(['design'])).map((folder) => folder.id)).toEqual(['archive', 'design', 'drafts']);
  });

  it('finds the current folder ancestry', () => {
    expect([...ancestorIds(folders, 'drafts')]).toEqual(['design']);
  });
});
