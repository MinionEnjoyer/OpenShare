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
    const rows = flattenVisibleTree(forest, new Set(['design']));
    expect(rows.map((folder) => folder.id)).toEqual(['archive', 'design', 'drafts']);
    expect(rows.map(({ id, depth, isLast, ancestorContinuations }) => ({ id, depth, isLast, ancestorContinuations }))).toEqual([
      { id: 'archive', depth: 0, isLast: false, ancestorContinuations: [] },
      { id: 'design', depth: 0, isLast: true, ancestorContinuations: [] },
      { id: 'drafts', depth: 1, isLast: true, ancestorContinuations: [false] },
    ]);
  });

  it('keeps ancestor continuation lines when a branch has later siblings', () => {
    const moreFolders: Folder[] = [
      ...folders,
      { id: 'z-last', parent_id: null, name: 'Z Last', color: '#ffffff', icon: 'Z' },
    ];
    const rows = flattenVisibleTree(buildFolderForest(moreFolders), new Set(['design']));
    expect(rows.find((folder) => folder.id === 'drafts')?.ancestorContinuations).toEqual([true]);
  });

  it('finds the current folder ancestry', () => {
    expect([...ancestorIds(folders, 'drafts')]).toEqual(['design']);
  });
});
