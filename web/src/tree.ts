import type { FlatFolderNode, Folder, FolderNode } from './types';

export function buildFolderForest(folders: Folder[]): FolderNode[] {
  const nodes = new Map(folders.map((folder) => [folder.id, { ...folder, children: [] as FolderNode[] }]));
  const roots: FolderNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.parent_id && nodes.get(node.parent_id);
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }

  const reachable = new Set<string>();
  const mark = (node: FolderNode) => {
    if (reachable.has(node.id)) return;
    reachable.add(node.id);
    node.children.forEach(mark);
  };
  roots.forEach(mark);
  for (const node of nodes.values()) {
    if (!reachable.has(node.id)) {
      roots.push(node);
      mark(node);
    }
  }

  const sorted = new Set<string>();
  const sort = (items: FolderNode[]) => {
    items.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
    items.forEach((item) => {
      if (sorted.has(item.id)) return;
      sorted.add(item.id);
      sort(item.children);
    });
  };
  sort(roots);
  return roots;
}

export function ancestorIds(folders: Folder[], folderId: string | null): Set<string> {
  const byId = new Map(folders.map((folder) => [folder.id, folder]));
  const ancestors = new Set<string>();
  let current = folderId ? byId.get(folderId) : undefined;
  while (current?.parent_id && !ancestors.has(current.parent_id)) {
    ancestors.add(current.parent_id);
    current = byId.get(current.parent_id);
  }
  return ancestors;
}

export function filterTreeIds(folders: Folder[], query: string): Set<string> | null {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return null;
  const byId = new Map(folders.map((folder) => [folder.id, folder]));
  const visible = new Set<string>();
  folders.forEach((folder) => {
    if (!folder.name.toLocaleLowerCase().includes(needle)) return;
    visible.add(folder.id);
    let parent = folder.parent_id ? byId.get(folder.parent_id) : undefined;
    while (parent && !visible.has(parent.id)) {
      visible.add(parent.id);
      parent = parent.parent_id ? byId.get(parent.parent_id) : undefined;
    }
  });
  return visible;
}

export function flattenVisibleTree(
  roots: FolderNode[],
  expanded: Set<string>,
  visibleIds: Set<string> | null = null,
): FlatFolderNode[] {
  const rows: FlatFolderNode[] = [];
  const walk = (nodes: FolderNode[], depth: number, parentId: string | null, ancestorContinuations: boolean[]) => {
    const visibleNodes = visibleIds ? nodes.filter((node) => visibleIds.has(node.id)) : nodes;
    visibleNodes.forEach((node, index) => {
      const isLast = index === visibleNodes.length - 1;
      rows.push({ ...node, depth, parentId, ancestorContinuations, isLast });
      if (node.children.length && (expanded.has(node.id) || visibleIds)) {
        walk(node.children, depth + 1, node.id, [...ancestorContinuations, !isLast]);
      }
    });
  };
  walk(roots, 0, null, []);
  return rows;
}
