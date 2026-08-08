const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

function fakeElement(tagName = 'DIV') {
  return {
    tagName,
    hidden: true,
    textContent: '',
    value: '',
    disabled: false,
    dataset: {},
    className: '',
    setAttribute() {},
    replaceChildren(...children) {
      this.textContent = children.map((child) => child.textContent || '').join('');
    },
  };
}

const busy = fakeElement();
const busyText = fakeElement();
const errorHost = fakeElement();
const errorText = fakeElement();
const elements = {
  'page-busy': busy,
  'page-busy-text': busyText,
  'page-error': errorHost,
  'page-error-text': errorText,
};
const windowListeners = {};
let visibleForms = [];

global.document = {
  getElementById: (id) => elements[id] || null,
  createElement: (tagName) => fakeElement(tagName.toUpperCase()),
  createTextNode: (text) => ({ textContent: text }),
  querySelectorAll: () => visibleForms,
  addEventListener() {},
};
global.window = {
  document: global.document,
  location: { assign() {} },
  fetch: async () => { throw new Error('unexpected fetch'); },
  setTimeout,
  clearTimeout,
  addEventListener(type, listener) { windowListeners[type] = listener; },
};

require(path.resolve(__dirname, '../../static/loading.js'));
const loading = global.window.OpenShareLoading;

function fakeForm() {
  const button = fakeElement('BUTTON');
  button.textContent = 'Create';
  const form = {
    action: 'https://share.example.test/folders',
    method: 'post',
    dataset: { loading: 'Creating folder…' },
    querySelector: () => button,
  };
  return { form, button };
}

function resetUi() {
  busy.hidden = true;
  errorHost.hidden = true;
  errorText.textContent = '';
  visibleForms = [];
}

test.beforeEach(resetUi);

test('failed async folder creation clears busy state, restores the button, and shows the server error', async () => {
  const { form, button } = fakeForm();
  const response = {
    ok: false,
    status: 400,
    statusText: 'Bad Request',
    clone: () => ({ json: async () => ({ detail: 'could not create folder' }) }),
  };

  const succeeded = await loading.submitAsyncForm(form, {
    fetch: async () => response,
    makeFormData: () => ({}),
  });

  assert.equal(succeeded, false);
  assert.equal(busy.hidden, true);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, 'Create');
  assert.equal(errorHost.hidden, false);
  assert.match(errorText.textContent, /Creating folder failed: could not create folder/);
});

test('successful async folder creation follows the resolved redirect', async () => {
  const { form } = fakeForm();
  let destination = '';
  const response = { ok: true, url: 'https://share.example.test/folder/new-id' };

  const succeeded = await loading.submitAsyncForm(form, {
    fetch: async () => response,
    makeFormData: () => ({}),
    navigate: (url) => { destination = url; },
  });

  assert.equal(succeeded, true);
  assert.equal(destination, response.url);
});

test('item navigation times out to a recoverable error instead of hanging forever', () => {
  let timeoutCallback;

  assert.equal(loading.navigateWithBusy('/i/item-1', 'Opening item…', {
    assign() {},
    setTimeout(callback) { timeoutCallback = callback; return 7; },
    clearTimeout() {},
    timeoutMs: 25,
  }), true);
  assert.equal(busy.hidden, false);

  timeoutCallback();

  assert.equal(busy.hidden, true);
  assert.equal(errorHost.hidden, false);
  assert.equal(errorText.textContent, 'Could not open this item. Please try again.');
});

test('pageshow clears bfcache-restored spinners and disabled submit buttons', () => {
  const { form, button } = fakeForm();
  visibleForms = [form];
  loading.pageBusy('Opening item…');
  loading.setFormBusy(form, 'Creating folder…');

  windowListeners.pageshow();

  assert.equal(busy.hidden, true);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, 'Create');
});

test('pageshow does not enable a form control that was disabled before loading', () => {
  const { form, button } = fakeForm();
  button.disabled = true;
  visibleForms = [form];
  loading.setFormBusy(form, 'Creating folder…');

  windowListeners.pageshow();

  assert.equal(button.disabled, true);
  assert.equal(button.textContent, 'Create');
});
