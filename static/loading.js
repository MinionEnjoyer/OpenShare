(function () {
  function spinner(size = 'sm', label = 'Loading') {
    const el = document.createElement('span');
    el.className = `oc-spinner oc-spinner--${size}`;
    el.setAttribute('role', 'status');
    el.setAttribute('aria-label', label);
    return el;
  }

  function pageBusy(label = 'Working…') {
    const host = document.getElementById('page-busy');
    const text = document.getElementById('page-busy-text');
    if (!host || !text) return;
    text.textContent = label;
    host.hidden = false;
  }

  function clearPageBusy() {
    const host = document.getElementById('page-busy');
    if (host) host.hidden = true;
  }

  function showError(message) {
    const host = document.getElementById('page-error');
    const text = document.getElementById('page-error-text');
    if (!host || !text) return;
    text.textContent = message;
    host.hidden = false;
  }

  function clearError() {
    const host = document.getElementById('page-error');
    if (host) host.hidden = true;
  }

  function setFormBusy(form, label) {
    const button = form.querySelector('button[type="submit"], input[type="submit"]');
    form.dataset.loadingBusy = 'true';
    if (!button) return;
    button.dataset.loadingOriginal = button.tagName === 'INPUT' ? button.value : button.textContent;
    button.dataset.loadingWasDisabled = button.disabled ? 'true' : 'false';
    button.disabled = true;
    if (button.tagName === 'BUTTON') {
      button.replaceChildren(spinner('xs', label), document.createTextNode(label));
    } else {
      button.value = label;
    }
  }

  function resetFormBusy(form) {
    const button = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!form.dataset.loadingBusy) return;
    delete form.dataset.loadingBusy;
    if (!button) return;
    const original = button.dataset.loadingOriginal;
    button.disabled = button.dataset.loadingWasDisabled === 'true';
    delete button.dataset.loadingWasDisabled;
    if (original !== undefined) {
      if (button.tagName === 'BUTTON') button.textContent = original;
      else button.value = original;
      delete button.dataset.loadingOriginal;
    }
  }

  async function responseError(response) {
    try {
      const body = await response.clone().json();
      if (typeof body.detail === 'string') return body.detail;
      if (typeof body.message === 'string') return body.message;
    } catch { /* fall through to status text */ }
    return response.statusText || `HTTP ${response.status}`;
  }

  async function submitAsyncForm(form, dependencies = {}) {
    if (form.dataset.loadingBusy) return false;
    const label = form.dataset.loading || 'Working…';
    const fetchImpl = dependencies.fetch || window.fetch.bind(window);
    const makeFormData = dependencies.makeFormData || ((target) => new FormData(target));
    const navigate = dependencies.navigate || ((url) => window.location.assign(url));
    clearError();
    pageBusy(label);
    setFormBusy(form, label);
    try {
      const response = await fetchImpl(form.action, {
        method: (form.method || 'post').toUpperCase(),
        body: makeFormData(form),
        credentials: 'same-origin',
      });
      if (!response.ok) throw new Error(await responseError(response));
      navigate(response.url || form.action);
      return true;
    } catch (error) {
      clearPageBusy();
      resetFormBusy(form);
      const operation = label.replace(/(?:…|\.\.\.)$/, '').trim();
      showError(`${operation} failed: ${error instanceof Error ? error.message : String(error)}`);
      return false;
    }
  }

  let cancelPendingNavigation = null;
  function navigateWithBusy(url, label = 'Opening…', dependencies = {}) {
    if (!url) return false;
    if (cancelPendingNavigation) cancelPendingNavigation();
    const assign = dependencies.assign || ((target) => window.location.assign(target));
    const setTimer = dependencies.setTimeout || window.setTimeout.bind(window);
    const clearTimer = dependencies.clearTimeout || window.clearTimeout.bind(window);
    const timeoutMs = dependencies.timeoutMs || 10000;
    clearError();
    pageBusy(label);
    let finished = false;
    const timeout = setTimer(() => {
      if (finished) return;
      finished = true;
      clearPageBusy();
      showError('Could not open this item. Please try again.');
    }, timeoutMs);
    const finish = () => {
      if (finished) return;
      finished = true;
      clearTimer(timeout);
    };
    cancelPendingNavigation = finish;
    window.addEventListener('pagehide', finish, { once: true });
    try {
      assign(url);
      return true;
    } catch (error) {
      finish();
      clearPageBusy();
      showError(`Could not open this item: ${error instanceof Error ? error.message : String(error)}`);
      return false;
    }
  }

  function initLoadingImages(root = document) {
    for (const img of root.querySelectorAll('img[data-loading-image]')) {
      if (img.dataset.loadingReady) continue;
      img.dataset.loadingReady = 'true';
      const host = img.parentElement;
      if (!host) continue;
      host.classList.add('loading-image-host');
      const mark = spinner(img.dataset.spinnerSize || 'sm', 'Loading image');
      host.prepend(mark);
      const finish = () => {
        host.classList.add('loaded');
        mark.remove();
      };
      if (img.complete) finish();
      else {
        img.addEventListener('load', finish, { once: true });
        img.addEventListener('error', finish, { once: true });
      }
    }
  }

  function initMediaLoaders(root = document) {
    for (const media of root.querySelectorAll('[data-loading-media]')) {
      const host = media.parentElement;
      if (!host || host.dataset.loadingReady) continue;
      host.dataset.loadingReady = 'true';
      const mark = spinner(media.dataset.spinnerSize || 'md', media.dataset.loadingLabel || 'Loading media');
      host.prepend(mark);
      const finish = () => {
        host.classList.add('loaded');
        mark.remove();
      };
      const event = media.tagName === 'VIDEO' ? 'loadeddata' : 'load';
      media.addEventListener(event, finish, { once: true });
      media.addEventListener('error', finish, { once: true });
      if ((media.tagName === 'IMG' && media.complete) || (media.tagName === 'VIDEO' && media.readyState >= 2)) finish();
    }
  }

  function initForms(root = document) {
    for (const form of root.querySelectorAll('form[data-loading]')) {
      if (form.dataset.loadingReady) continue;
      form.dataset.loadingReady = 'true';
      if (form.dataset.asyncForm !== undefined) {
        form.addEventListener('submit', (event) => {
          event.preventDefault();
          void submitAsyncForm(form);
        });
        continue;
      }
      form.addEventListener('submit', (event) => {
        queueMicrotask(() => {
          if (event.defaultPrevented) return;
          const label = form.dataset.loading || 'Working…';
          pageBusy(label);
          setFormBusy(form, label);
        });
      });
    }
    for (const link of root.querySelectorAll('[data-loading-link]')) {
      link.addEventListener('click', () => pageBusy(link.dataset.loadingLink || 'Loading…'));
    }
  }

  window.OpenShareLoading = {
    spinner, pageBusy, clearPageBusy, showError, clearError,
    setFormBusy, resetFormBusy, submitAsyncForm, navigateWithBusy,
    initLoadingImages, initMediaLoaders,
  };
  document.addEventListener('DOMContentLoaded', () => {
    initLoadingImages();
    initMediaLoaders();
    initForms();
  });
  window.addEventListener('pageshow', () => {
    if (cancelPendingNavigation) cancelPendingNavigation();
    cancelPendingNavigation = null;
    clearPageBusy();
    for (const form of document.querySelectorAll('form[data-loading]')) resetFormBusy(form);
  });
})();
