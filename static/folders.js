(function (global) {
  'use strict';

  const HEX_COLOR = /^#[0-9a-f]{6}$/i;

  function clampByte(value) {
    const number = Number.parseInt(value, 10);
    return Math.min(255, Math.max(0, Number.isFinite(number) ? number : 0));
  }

  function normalizeHex(value) {
    const normalized = String(value || '').trim().toLowerCase();
    return HEX_COLOR.test(normalized) ? normalized : null;
  }

  function hexToRgb(value) {
    const hex = normalizeHex(value);
    if (!hex) return null;
    return {
      r: Number.parseInt(hex.slice(1, 3), 16),
      g: Number.parseInt(hex.slice(3, 5), 16),
      b: Number.parseInt(hex.slice(5, 7), 16),
    };
  }

  function rgbToHex(red, green, blue) {
    return `#${[red, green, blue].map((part) => clampByte(part).toString(16).padStart(2, '0')).join('')}`;
  }

  function filterEmojiChoices(query, choices) {
    const needle = String(query || '').trim().toLowerCase();
    return choices.filter((choice) => !needle || choice.label.toLowerCase().includes(needle) || choice.emoji.includes(needle));
  }

  function buildFolderForest(folders) {
    const nodes = new Map(folders.map((folder) => [folder.id, { ...folder, children: [] }]));
    const roots = [];
    for (const node of nodes.values()) {
      const parent = node.parent_id && nodes.get(node.parent_id);
      if (parent && parent !== node) parent.children.push(node);
      else roots.push(node);
    }
    const reachable = new Set();
    function mark(node) {
      if (reachable.has(node.id)) return;
      reachable.add(node.id);
      node.children.forEach(mark);
    }
    roots.forEach(mark);
    for (const node of nodes.values()) {
      if (!reachable.has(node.id)) {
        roots.push(node);
        mark(node);
      }
    }
    const sorted = new Set();
    const sort = (items) => {
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

  function initFolderTree(root) {
    const host = root.querySelector('[data-folder-tree]');
    const source = root.querySelector('[data-folder-tree-source]');
    const search = root.querySelector('[data-folder-tree-search]');
    if (!host || !source) return;
    let folders;
    try { folders = JSON.parse(source.textContent); } catch { return; }
    const currentFolder = String(host.dataset.currentFolder || '');
    const seen = new Set();

    function renderNodes(nodes, depth = 0) {
      const list = document.createElement('ul');
      list.className = depth ? 'folder-tree-children' : 'folder-tree-root';
      list.setAttribute('role', depth ? 'group' : 'tree');
      nodes.forEach((node) => {
        if (seen.has(node.id)) return;
        seen.add(node.id);
        const item = document.createElement('li');
        item.setAttribute('role', 'treeitem');
        item.dataset.treeLabel = node.name.toLowerCase();
        const row = document.createElement('div');
        row.className = 'folder-tree-row';
        let childList = null;
        if (node.children.length) {
          const expand = document.createElement('button');
          expand.type = 'button';
          expand.className = 'folder-tree-expand';
          expand.textContent = '▾';
          expand.setAttribute('aria-label', `Collapse ${node.name}`);
          expand.setAttribute('aria-expanded', 'true');
          expand.addEventListener('click', () => {
            const expanded = expand.getAttribute('aria-expanded') === 'true';
            expand.setAttribute('aria-expanded', String(!expanded));
            expand.setAttribute('aria-label', `${expanded ? 'Expand' : 'Collapse'} ${node.name}`);
            expand.textContent = expanded ? '▸' : '▾';
            childList.hidden = expanded;
          });
          row.append(expand);
        } else {
          const spacer = document.createElement('span');
          spacer.className = 'folder-tree-spacer';
          row.append(spacer);
        }
        const link = document.createElement('a');
        link.href = `/folder/${encodeURIComponent(node.id)}`;
        link.className = 'folder-tree-link';
        link.dataset.loadingLink = 'Opening folder…';
        if (String(node.id) === currentFolder) {
          link.classList.add('current');
          link.setAttribute('aria-current', 'page');
        }
        const icon = document.createElement('span');
        icon.className = 'folder-tree-icon';
        icon.textContent = node.icon;
        icon.style.setProperty('--folder-color', node.color || '#4f9cf9');
        const name = document.createElement('span');
        name.textContent = node.name;
        link.append(icon, name);
        row.append(link);
        item.append(row);
        if (node.children.length) {
          childList = renderNodes(node.children, depth + 1);
          item.append(childList);
        }
        list.append(item);
      });
      return list;
    }
    const home = document.createElement('a');
    home.href = '/';
    home.className = 'folder-tree-home';
    home.dataset.loadingLink = 'Opening library…';
    if (!currentFolder) {
      home.classList.add('current');
      home.setAttribute('aria-current', 'page');
    }
    const homeIcon = document.createElement('span');
    homeIcon.className = 'folder-tree-icon folder-tree-icon-home';
    homeIcon.textContent = '⌂';
    const homeLabel = document.createElement('span');
    homeLabel.textContent = 'All files';
    home.append(homeIcon, homeLabel);
    host.replaceChildren(home, renderNodes(buildFolderForest(folders)));
    search?.addEventListener('input', () => {
      const query = search.value.trim().toLowerCase();
      const items = [...host.querySelectorAll('li[data-tree-label]')];
      for (let index = items.length - 1; index >= 0; index -= 1) {
        const item = items[index];
        const selfMatches = !query || item.dataset.treeLabel.includes(query);
        const childMatches = [...item.querySelectorAll(':scope > ul > li')].some((child) => !child.hidden);
        item.hidden = !selfMatches && !childMatches;
      }
      host.querySelectorAll('.folder-tree-children').forEach((list) => { if (query) list.hidden = false; });
    });
  }

  function updatePreview(control, color, emoji) {
    const preview = control.closest('form')?.querySelector('[data-folder-preview]');
    if (!preview) return;
    if (color) preview.style.setProperty('--folder-color', color);
    if (emoji) preview.textContent = emoji;
  }

  function initColorControl(control) {
    const value = control.querySelector('[data-color-value]');
    const well = control.querySelector('[data-color-well]');
    const hex = control.querySelector('[data-color-hex]');
    const channels = Object.fromEntries(
      [...control.querySelectorAll('[data-rgb]')].map((input) => [input.dataset.rgb, input]),
    );
    if (!value || !well || !hex || !channels.r || !channels.g || !channels.b) return;

    function render(color) {
      const normalized = normalizeHex(color);
      const rgb = normalized && hexToRgb(normalized);
      if (!normalized || !rgb) return false;
      value.value = normalized;
      well.value = normalized;
      hex.value = normalized;
      channels.r.value = rgb.r;
      channels.g.value = rgb.g;
      channels.b.value = rgb.b;
      updatePreview(control, normalized, null);
      return true;
    }

    render(value.value || '#4f9cf9');
    well.addEventListener('input', () => render(well.value));
    hex.addEventListener('input', () => {
      const valid = render(hex.value);
      hex.setAttribute('aria-invalid', valid ? 'false' : 'true');
    });
    for (const input of Object.values(channels)) {
      input.addEventListener('input', () => render(rgbToHex(channels.r.value, channels.g.value, channels.b.value)));
    }
  }

  function closeEmojiPicker(picker) {
    const trigger = picker.querySelector('[data-emoji-trigger]');
    const popout = picker.querySelector('[data-emoji-popout]');
    if (!trigger || !popout) return;
    popout.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
  }

  function initEmojiPicker(picker) {
    const trigger = picker.querySelector('[data-emoji-trigger]');
    const popout = picker.querySelector('[data-emoji-popout]');
    const search = picker.querySelector('[data-emoji-search]');
    const value = picker.querySelector('[data-emoji-value]');
    const current = picker.querySelector('[data-emoji-current]');
    const empty = picker.querySelector('[data-emoji-empty]');
    const options = [...picker.querySelectorAll('[data-emoji]')];
    if (!trigger || !popout || !search || !value || !current) return;

    trigger.addEventListener('click', () => {
      const opening = popout.hidden;
      document.querySelectorAll('[data-emoji-picker]').forEach((other) => {
        if (other !== picker) closeEmojiPicker(other);
      });
      popout.hidden = !opening;
      trigger.setAttribute('aria-expanded', String(opening));
      if (opening) search.focus();
    });
    search.addEventListener('input', () => {
      const visible = filterEmojiChoices(search.value, options.map((option) => ({
        emoji: option.dataset.emoji,
        label: option.dataset.label,
        option,
      })));
      const shown = new Set(visible.map((choice) => choice.option));
      options.forEach((option) => { option.hidden = !shown.has(option); });
      if (empty) empty.hidden = shown.size > 0;
    });
    options.forEach((option) => option.addEventListener('click', () => {
      value.value = option.dataset.emoji;
      current.textContent = option.dataset.emoji;
      options.forEach((candidate) => candidate.setAttribute('aria-selected', String(candidate === option)));
      updatePreview(picker, null, option.dataset.emoji);
      closeEmojiPicker(picker);
    }));
  }

  function setEditMode(enabled, root = document) {
    const button = root.getElementById('folder-edit-toggle');
    root.body?.classList.toggle('folder-editing', enabled);
    root.querySelectorAll?.('.folder-edit-action, .folder-tile-edit').forEach((control) => {
      control.hidden = !enabled;
    });
    if (button) {
      button.setAttribute('aria-pressed', String(enabled));
      const label = button.querySelector('[data-edit-label]');
      if (label) label.textContent = enabled ? 'Done editing' : 'Edit folders';
    }
    return enabled;
  }

  function initFolders(root = document) {
    root.querySelectorAll('[data-folder-appearance]').forEach(initColorControl);
    root.querySelectorAll('[data-emoji-picker]').forEach(initEmojiPicker);
    root.querySelectorAll('.folder-tree-dialog').forEach(initFolderTree);
    const toggle = root.getElementById('folder-edit-toggle');
    if (toggle) setEditMode(false, root);
    toggle?.addEventListener('click', () => setEditMode(toggle.getAttribute('aria-pressed') !== 'true', root));
    root.querySelectorAll('[data-open-dialog]').forEach((button) => button.addEventListener('click', () => {
      root.getElementById(button.dataset.openDialog)?.showModal();
    }));
    root.querySelectorAll('[data-dialog-close]').forEach((button) => button.addEventListener('click', () => {
      button.closest('dialog')?.close();
    }));
    root.addEventListener('click', (event) => {
      if (!event.target.closest('[data-emoji-picker]')) {
        root.querySelectorAll('[data-emoji-picker]').forEach(closeEmojiPicker);
      }
    });
    root.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') root.querySelectorAll('[data-emoji-picker]').forEach(closeEmojiPicker);
    });
  }

  const api = { normalizeHex, hexToRgb, rgbToHex, filterEmojiChoices, buildFolderForest, setEditMode, initFolders };
  global.OpenShareFolders = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (global.document) global.document.addEventListener('DOMContentLoaded', () => initFolders(global.document));
})(typeof window !== 'undefined' ? window : globalThis);
