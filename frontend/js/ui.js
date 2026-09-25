/**
 * Small UI helpers: toast notifications, a generic modal, skeleton-loader
 * markup, and empty/error state blocks. No framework — plain DOM + strings.
 */

import { ICONS } from './icons.js';

// --- Toasts ------------------------------------------------------------

let toastStack = null;

function ensureToastStack() {
  if (toastStack && document.body.contains(toastStack)) return toastStack;
  toastStack = document.createElement('div');
  toastStack.className = 'toast-stack';
  document.body.appendChild(toastStack);
  return toastStack;
}

export function toast(message, type = 'info', duration = 4200) {
  const stack = ensureToastStack();
  const el = document.createElement('div');
  el.className = `toast toast--${type}`;
  el.setAttribute('role', 'status');
  el.textContent = message;
  stack.appendChild(el);

  const remove = () => {
    el.style.transition = 'opacity 180ms ease';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 180);
  };
  const timer = setTimeout(remove, duration);
  el.addEventListener('click', () => {
    clearTimeout(timer);
    remove();
  });
  return el;
}

export const toastSuccess = (msg) => toast(msg, 'success');
export const toastError = (msg) => toast(msg, 'error');
export const toastInfo = (msg) => toast(msg, 'info');

// --- Modal ---------------------------------------------------------------

export function openModal(bodyEl, { closeOnScrim = true, maxWidth } = {}) {
  const scrim = document.createElement('div');
  scrim.className = 'modal-scrim';

  const modal = document.createElement('div');
  modal.className = 'modal';
  if (maxWidth) modal.style.maxWidth = maxWidth;
  modal.appendChild(bodyEl);
  scrim.appendChild(modal);
  document.body.appendChild(scrim);

  function onKey(e) {
    if (e.key === 'Escape') close();
  }

  function close() {
    document.removeEventListener('keydown', onKey);
    scrim.remove();
  }

  document.addEventListener('keydown', onKey);
  if (closeOnScrim) {
    scrim.addEventListener('click', (e) => {
      if (e.target === scrim) close();
    });
  }

  return { close, scrim, modal };
}

// --- Skeleton loaders ------------------------------------------------------

export const skeleton = {
  text: () => '<div class="skeleton skeleton--text"></div>',
  kpiRow: (count = 4) =>
    `<div class="grid grid--kpi">${'<div class="skeleton skeleton--kpi"></div>'.repeat(count)}</div>`,
  block: (height = 220) => `<div class="skeleton skeleton--block" style="height:${height}px"></div>`,
  line: () => '<div class="skeleton skeleton--line"></div>',
};

// --- Empty / error states ---------------------------------------------------

/** A slightly larger, friendlier illustration for prominent empty states
 * (e.g. "no predictions yet") — same monoline style as ICONS, just bigger. */
export const ILLUSTRATIONS = {
  noPredictions: `
    <svg class="state-block__illustration" viewBox="0 0 96 96" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M48 14C48 14 27 40 27 55a21 21 0 0 0 42 0c0-15-21-41-21-41Z"/>
      <path d="M39 56l6 6 12-14"/>
      <path d="M18 78h60" stroke-dasharray="1 7"/>
    </svg>
  `,
};

export function emptyState({ icon = ICONS.inbox, illustration, title, desc = '', actionLabel, onAction } = {}) {
  const wrap = document.createElement('div');
  wrap.className = 'state-block';
  wrap.innerHTML = `${illustration || icon}<div class="state-block__title">${title}</div>${
    desc ? `<div class="state-block__desc">${desc}</div>` : ''
  }`;
  if (actionLabel && onAction) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn--primary btn--sm';
    btn.textContent = actionLabel;
    btn.addEventListener('click', onAction);
    wrap.appendChild(btn);
  }
  return wrap;
}

export function errorState({ message = 'Something went wrong.', onRetry } = {}) {
  const wrap = document.createElement('div');
  wrap.className = 'state-block state-block--error';
  wrap.innerHTML = `${ICONS.alertTriangle}<div class="state-block__title">Couldn't load this</div><div class="state-block__desc"></div>`;
  wrap.querySelector('.state-block__desc').textContent = message;
  if (onRetry) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn--sm';
    btn.innerHTML = `${ICONS.refresh}<span>Retry</span>`;
    btn.addEventListener('click', onRetry);
    wrap.appendChild(btn);
  }
  return wrap;
}

// --- Expand / collapse toggle ------------------------------------------

/** Wires every `[data-expand-toggle]` button inside `container` to show/hide
 * the element with the matching id (searched in `container` first, falling
 * back to the whole document — a table row's expand target can't always be
 * a DOM descendant of the button, e.g. inside a `<td>`). Toggles
 * `aria-expanded` on the button and `.is-open` on any `[data-expand-caret]`
 * child for a rotating chevron. Call once, right after inserting markup
 * built from riskExpandableMarkup() (frontend/js/riskUi.js) or similar. */
export function wireExpandToggles(container) {
  container.querySelectorAll('[data-expand-toggle]').forEach((btn) => {
    const targetId = btn.dataset.expandToggle;
    const target = container.querySelector(`#${targetId}`) || document.getElementById(targetId);
    if (!target) return;
    btn.addEventListener('click', () => {
      const wasHidden = target.hidden;
      target.hidden = !wasHidden;
      btn.setAttribute('aria-expanded', String(wasHidden));
      btn.querySelectorAll('[data-expand-caret]').forEach((caret) => caret.classList.toggle('is-open', wasHidden));
    });
  });
}

// --- Misc --------------------------------------------------------------

export function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = String(value ?? '');
  return div.innerHTML;
}

/** Short relative-time label ("just now", "32s ago", "3 min ago", "2 hr
 * ago", "5 d ago"), falling back to a locale date beyond a week. Shared by
 * the "Updated Xs ago" live indicator and the recent-predictions list. */
export function relativeTime(input) {
  const date = input instanceof Date ? input : new Date(input);
  const sec = Math.round((Date.now() - date.getTime()) / 1000);
  if (sec < 5) return 'just now';
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} hr ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day} d ago`;
  return date.toLocaleDateString();
}
