const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const folders = require(path.resolve(__dirname, '../../static/folders.js'));

test('RGB and hex folder colors round-trip without changing the selected color', () => {
  assert.deepEqual(folders.hexToRgb('#12AbEf'), { r: 18, g: 171, b: 239 });
  assert.equal(folders.rgbToHex(18, 171, 239), '#12abef');
  assert.equal(folders.normalizeHex(' #12ABEF '), '#12abef');
});

test('RGB values are clamped to valid bytes', () => {
  assert.equal(folders.rgbToHex(-4, 300, '32'), '#00ff20');
  assert.equal(folders.normalizeHex('red'), null);
});

test('emoji search matches labels case-insensitively', () => {
  const choices = [
    { emoji: '📁', label: 'Folder' },
    { emoji: '📷', label: 'Camera' },
    { emoji: '🎵', label: 'Music' },
  ];
  assert.deepEqual(folders.filterEmojiChoices('CAM', choices), [choices[1]]);
  assert.deepEqual(folders.filterEmojiChoices('', choices), choices);
});

test('folder tree builds a sorted hierarchy and keeps orphaned folders accessible', () => {
  const forest = folders.buildFolderForest([
    { id: 'child', parent_id: 'root', name: 'Child', icon: '📁' },
    { id: 'orphan', parent_id: 'missing', name: 'Archive', icon: '🗃️' },
    { id: 'root', parent_id: null, name: 'Projects', icon: '🧰' },
  ]);

  assert.deepEqual(forest.map((folder) => folder.id), ['orphan', 'root']);
  assert.deepEqual(forest[1].children.map((folder) => folder.id), ['child']);
});

test('folder tree breaks corrupt cycles into an accessible root', () => {
  const forest = folders.buildFolderForest([
    { id: 'a', parent_id: 'b', name: 'A', icon: '📁' },
    { id: 'b', parent_id: 'a', name: 'B', icon: '📁' },
  ]);

  assert.equal(forest.length, 1);
  assert.equal(forest[0].id, 'a');
});

test('folder edit mode updates the shared toggle and page state', () => {
  const classes = new Set();
  const label = { textContent: '' };
  const attributes = {};
  const button = {
    setAttribute(name, value) { attributes[name] = value; },
    querySelector() { return label; },
  };
  const editControls = [{ hidden: true }, { hidden: true }];
  const root = {
    body: { classList: { toggle(name, on) { if (on) classes.add(name); else classes.delete(name); } } },
    getElementById() { return button; },
    querySelectorAll() { return editControls; },
  };

  folders.setEditMode(true, root);
  assert.equal(attributes['aria-pressed'], 'true');
  assert.equal(label.textContent, 'Done editing');
  assert.equal(classes.has('folder-editing'), true);
  assert.deepEqual(editControls.map((control) => control.hidden), [false, false]);

  folders.setEditMode(false, root);
  assert.deepEqual(editControls.map((control) => control.hidden), [true, true]);
});
