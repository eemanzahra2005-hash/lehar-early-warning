/**
 * Minimal hash router. Each route maps to a mount(root) function that
 * renders into #view-root and may return a cleanup function (called before
 * the next view mounts, e.g. to clear polling intervals).
 */

const routes = new Map();
const DEFAULT_PATH = '/dashboard';
let currentCleanup = null;

export function registerRoute(path, mountFn) {
  routes.set(path, mountFn);
}

function currentPath() {
  const hash = window.location.hash.replace(/^#/, '');
  return hash || DEFAULT_PATH;
}

function updateActiveNav(path) {
  document.querySelectorAll('.nav__link').forEach((link) => {
    link.classList.toggle('is-active', link.getAttribute('href') === `#${path}`);
  });
}

async function render() {
  if (typeof currentCleanup === 'function') {
    try {
      currentCleanup();
    } catch (err) {
      console.error('view cleanup failed', err);
    }
  }
  currentCleanup = null;

  const root = document.getElementById('view-root');
  if (!root) return;

  const path = currentPath();
  const mountFn = routes.get(path) || routes.get(DEFAULT_PATH);
  root.innerHTML = '';
  updateActiveNav(routes.has(path) ? path : DEFAULT_PATH);

  try {
    const result = await mountFn(root);
    if (typeof result === 'function') currentCleanup = result;
  } catch (err) {
    console.error('view mount failed', err);
  }

  // Restart the fade-in on every navigation — the class stays in the
  // stylesheet, so without forcing reflow it wouldn't replay on a node
  // that's already had it applied once.
  root.classList.remove('view-fade-in');
  void root.offsetWidth;
  root.classList.add('view-fade-in');

  document.getElementById('main')?.scrollTo({ top: 0 });
}

export function startRouter() {
  window.addEventListener('hashchange', render);
  render();
}

export function navigate(path) {
  window.location.hash = `#${path}`;
}
