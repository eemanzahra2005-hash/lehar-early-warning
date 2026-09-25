/**
 * Ctrl+K / Cmd+K command palette — jump to any page or switch district.
 * Vanilla JS, no library: a simple in-order subsequence fuzzy match, arrow
 * keys + Enter to select, Esc/scrim-click to close.
 */

import { escapeHtml } from './ui.js';

/** In-order subsequence match: every query char must appear in target, in
 * order (not necessarily contiguous). Consecutive matches score higher so
 * "lah" ranks "Lahore" above a scattered match. Returns -1 for no match. */
function fuzzyScore(query, target) {
  const q = query.toLowerCase();
  const t = target.toLowerCase();
  if (!q) return 0;
  let qi = 0;
  let score = 0;
  let lastIndex = -2;
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) {
      score += lastIndex === ti - 1 ? 3 : 1;
      lastIndex = ti;
      qi++;
    }
  }
  return qi === q.length ? score - t.length * 0.01 : -1;
}

export function initCommandPalette({ pages = [], getDistricts = () => [], onNavigate, onSelectDistrict }) {
  let scrim = null;
  let input = null;
  let list = null;
  let items = [];
  let activeIndex = 0;

  function buildItems() {
    const pageItems = pages.map((p) => ({ type: 'page', label: p.label, sub: 'Go to page', path: p.path, icon: p.icon }));
    const districtItems = getDistricts().map((d) => ({ type: 'district', label: d, sub: 'Switch district', value: d }));
    return [...pageItems, ...districtItems];
  }

  function close() {
    document.removeEventListener('keydown', onKeydown);
    if (scrim) scrim.remove();
    scrim = null;
    input = null;
    list = null;
  }

  function selectItem(item) {
    if (!item) return;
    close();
    if (item.type === 'page') onNavigate(item.path);
    else onSelectDistrict(item.value);
  }

  function setActive(index) {
    if (!items.length) return;
    activeIndex = (index + items.length) % items.length;
    list.querySelectorAll('.cmdk__item').forEach((el, i) => el.classList.toggle('is-active', i === activeIndex));
    const activeEl = list.children[activeIndex];
    if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
  }

  function renderList(query) {
    const all = buildItems();
    const filtered = query
      ? all
          .map((item) => ({ item, score: fuzzyScore(query, item.label) }))
          .filter((r) => r.score >= 0)
          .sort((a, b) => b.score - a.score)
          .map((r) => r.item)
      : all;
    items = filtered.slice(0, 30);
    activeIndex = 0;

    list.innerHTML = items.length
      ? items
          .map(
            (item, i) => `
              <button type="button" class="cmdk__item ${i === 0 ? 'is-active' : ''}" data-index="${i}">
                ${item.icon || ''}
                <span class="cmdk__item-label">${escapeHtml(item.label)}</span>
                <span class="cmdk__item-sub">${escapeHtml(item.sub)}</span>
              </button>
            `
          )
          .join('')
      : `<div class="cmdk__empty">No matches.</div>`;

    list.querySelectorAll('.cmdk__item').forEach((el) => {
      const i = Number(el.dataset.index);
      el.addEventListener('click', () => selectItem(items[i]));
      el.addEventListener('mousemove', () => setActive(i));
    });
  }

  function onKeydown(e) {
    if (e.key === 'Escape') {
      close();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive(activeIndex + 1);
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive(activeIndex - 1);
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      selectItem(items[activeIndex]);
    }
  }

  function open() {
    if (scrim) {
      input.focus();
      return;
    }
    scrim = document.createElement('div');
    scrim.className = 'cmdk-scrim';
    scrim.innerHTML = `
      <div class="cmdk" role="dialog" aria-label="Command palette">
        <div class="cmdk__input-row">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input class="cmdk__input" type="text" placeholder="Jump to a page or district…" autocomplete="off" />
        </div>
        <div class="cmdk__list"></div>
        <div class="cmdk__hint">&uarr;&darr; navigate &middot; Enter select &middot; Esc close</div>
      </div>
    `;
    document.body.appendChild(scrim);
    input = scrim.querySelector('.cmdk__input');
    list = scrim.querySelector('.cmdk__list');

    scrim.addEventListener('click', (e) => {
      if (e.target === scrim) close();
    });
    input.addEventListener('input', () => renderList(input.value.trim()));
    document.addEventListener('keydown', onKeydown);

    renderList('');
    input.focus();
  }

  document.addEventListener('keydown', (e) => {
    if ((e.key === 'k' || e.key === 'K') && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      scrim ? close() : open();
    }
  });

  return { open, close };
}
