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
  appVersion: string;
  openChatConnected: boolean;
};

export type LibraryItem = {
  id: string;
  name: string;
  mediaType: string;
  thumbUrl: string | null;
  viewUrl: string;
  extension: string;
};

export type LibraryData = FolderWorkspaceData & {
  breadcrumb: Array<{ id: string; name: string }>;
  items: LibraryItem[];
};

export type FolderNode = Folder & { children: FolderNode[] };

export type FlatFolderNode = FolderNode & {
  depth: number;
  parentId: string | null;
  ancestorContinuations: boolean[];
  isLast: boolean;
};

export type MediaViewerData = {
  id: string;
  name: string;
  mediaType: 'image' | 'video' | 'audio' | 'pdf' | 'text' | 'archive' | 'model' | 'spreadsheet';
  rawUrl: string;
  thumbUrl: string | null;
  ownerUsername: string;
  sizeLabel: string;
  appVersion: string;
  canManage: boolean;
  backUrl: string;
  deleteUrl: string;
  shareUrl: string;
  waveformUrl: string | null;
  spreadsheetUrl: string | null;
  textBody: string | null;
  textLanguage: string | null;
  textTruncated: boolean;
  modelExtension: string | null;
  modelMaterial: string | null;
  navigation: {
    position: number;
    total: number;
    previous: MediaViewerSibling | null;
    next: MediaViewerSibling | null;
  } | null;
};

export type MediaViewerSibling = {
  id: string;
  name: string;
  mediaType: MediaViewerData['mediaType'];
  viewUrl: string;
};
