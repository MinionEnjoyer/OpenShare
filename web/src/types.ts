export type Folder = {
  id: string;
  name: string;
  parent_id: string | null;
  color: string;
  icon: string;
  preview_mode?: 'icon' | 'dynamic' | 'custom';
  preview_media_id?: string | null;
  preview_images?: FolderPreviewImage[];
  child_count?: number;
  item_count?: number;
};

export type FolderPreviewImage = { id: string; name: string; thumb_url: string };

export type FolderWorkspaceData = {
  currentFolder: Folder | null;
  subfolders: Folder[];
  allFolders: Folder[];
  publicUrl: string;
  appVersion: string;
  openChatConnected: boolean;
};

export type FolderNode = Folder & { children: FolderNode[] };

export type FlatFolderNode = FolderNode & {
  depth: number;
  parentId: string | null;
};
