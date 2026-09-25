// Applied before first paint to avoid a light-theme flash for users who last
// chose dark (or vice versa) — kept tiny and loaded as a plain blocking
// <script src> (not type="module") in index.html's <head> so it runs before
// any DOM renders. Externalized from an inline <script> block (Phase 11) so
// the app's Content-Security-Policy can use `script-src 'self'` with no
// 'unsafe-inline'/nonce exception — see backend/app/middleware.py.
(function () {
  // Must stay in sync with state.js's THEME_KEY.
  var saved = localStorage.getItem('lehar_theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
})();
