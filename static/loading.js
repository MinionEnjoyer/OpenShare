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
      form.addEventListener('submit', (event) => {
        queueMicrotask(() => {
          if (event.defaultPrevented) return;
          const button = form.querySelector('button[type="submit"], input[type="submit"]');
          const label = form.dataset.loading || 'Working…';
          pageBusy(label);
          if (button instanceof HTMLButtonElement) {
            button.disabled = true;
            button.replaceChildren(spinner('xs', label), document.createTextNode(label));
          } else if (button instanceof HTMLInputElement) {
            button.disabled = true;
            button.value = label;
          }
        });
      });
    }
    for (const link of root.querySelectorAll('[data-loading-link]')) {
      link.addEventListener('click', () => pageBusy(link.dataset.loadingLink || 'Loading…'));
    }
  }

  window.OpenShareLoading = { spinner, pageBusy, clearPageBusy, initLoadingImages, initMediaLoaders };
  document.addEventListener('DOMContentLoaded', () => {
    initLoadingImages();
    initMediaLoaders();
    initForms();
  });
})();
