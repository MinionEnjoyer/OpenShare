import React from 'react';
import { createRoot } from 'react-dom/client';
import { FolderWorkspace } from './FolderWorkspace';
import type { FolderWorkspaceData } from './types';
import './workspace.css';
import { applyTheme, storedTheme } from './theme';

const root = document.getElementById('folder-workspace');
const source = document.getElementById('folder-workspace-data');

if (root && source?.textContent) {
  applyTheme(storedTheme());
  const data = JSON.parse(source.textContent) as FolderWorkspaceData;
  createRoot(root).render(<React.StrictMode><FolderWorkspace data={data} /></React.StrictMode>);
}
