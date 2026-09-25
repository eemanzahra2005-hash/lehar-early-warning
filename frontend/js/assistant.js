/**
 * LEHAR Assistant (Phase 6.5) — floating chat button + slide-in panel,
 * present on every page. Talks to a local Ollama model through
 * POST /api/v1/assistant/chat; every reply is grounded ONLY in real app
 * data (see backend/app/services/assistant.py) — this module never invents
 * anything, it just renders what the API returns and shows the exact
 * CONTEXT JSON under a collapsible "Data used" card. If the assistant is
 * offline, the panel shows a friendly inline state and disables the input —
 * the rest of the app is entirely unaffected either way.
 */

import { getAssistantStatus, assistantChat } from './api.js';
import { state, getLlmProviderPreference } from './state.js';
import { ICONS } from './icons.js';
import { escapeHtml, emptyState, wireExpandToggles } from './ui.js';

const SUGGESTIONS = ['Should I irrigate tomorrow?', 'Mera flood risk kya hai?', 'Explain my last prediction'];

let initialized = false;
let fabEl = null;
let scrimEl = null;
let panelEl = null;
let isOpen = false;
let statusInfo = null;
let sending = false;
let messages = []; // { id, role: 'user'|'assistant'|'error', text, contextUsed? }
let msgIdCounter = 0;

function dataUsedMarkup(contextUsed, id) {
  if (!contextUsed || Object.keys(contextUsed).length === 0) return '';
  return `
    <div class="assistant-data-used">
      <button type="button" class="assistant-data-used__trigger" data-expand-toggle="assistant-ctx-${id}" aria-expanded="false">
        ${ICONS.chevronDown}<span>Data used</span>
      </button>
      <div class="assistant-data-used__body" id="assistant-ctx-${id}" hidden>
        <pre class="assistant-data-used__json">${escapeHtml(JSON.stringify(contextUsed, null, 2))}</pre>
      </div>
    </div>
  `;
}

function providerBadgeMarkup(m) {
  if (!m.providerUsed) return '';
  const chipClass = m.providerUsed === 'cloud' ? 'chip--sky' : 'chip--emerald';
  const label = `${m.providerUsed} · ${m.model || ''}`;
  return `<span class="chip ${chipClass}">${escapeHtml(label)}</span>`;
}

function typingIndicatorMarkup() {
  return `
    <div class="assistant-typing">
      <span class="assistant-typing__dots"><span></span><span></span><span></span></span>
      <span>Thinking…</span>
    </div>
  `;
}

function renderMessages() {
  const el = panelEl.querySelector('#assistant-messages');

  if (messages.length === 0 && !sending) {
    el.innerHTML = '';
    el.appendChild(
      emptyState({
        icon: ICONS.chat,
        title: 'Ask me anything',
        desc: 'Real weather, irrigation, and flood data for any district — try a quick suggestion below.',
      })
    );
    return;
  }

  const turns = messages
    .map((m) => {
      if (m.role === 'user') {
        return `<div class="assistant-turn assistant-turn--user"><div class="assistant-bubble">${escapeHtml(m.text)}</div></div>`;
      }
      if (m.role === 'error') {
        return `<div class="assistant-turn assistant-turn--assistant"><div class="assistant-bubble assistant-bubble--error">${escapeHtml(m.text)}</div></div>`;
      }
      return `
        <div class="assistant-turn assistant-turn--assistant">
          <div class="assistant-bubble">${escapeHtml(m.text)}</div>
          ${providerBadgeMarkup(m)}
          ${dataUsedMarkup(m.contextUsed, m.id)}
        </div>
      `;
    })
    .join('');

  el.innerHTML = turns + (sending ? typingIndicatorMarkup() : '');
  wireExpandToggles(el);
  el.scrollTop = el.scrollHeight;
}

function offlineStateEl() {
  return emptyState({
    icon: ICONS.chat,
    title: 'AI assistant offline',
    desc: 'Add a free Groq API key (console.groq.com) to backend\\.env as LLM_CLOUD_API_KEY, or install Ollama — see RUN-ME-FIRST.txt. Everything else in the app works normally without it.',
  });
}

/** "Online · cloud + local", "Online · cloud only", "Offline" — summarizes
 * the two-provider status shape (see AssistantStatusResponse) into one
 * short label for the panel header. */
function statusSummaryLabel(info) {
  if (!info) return 'Checking…';
  if (!info.available) return 'Offline';
  const parts = [];
  if (info.cloud?.available) parts.push('cloud');
  if (info.local?.available) parts.push('local');
  return `Online · ${parts.join(' + ') || info.mode}`;
}

function render() {
  if (!panelEl) return;
  const statusLabel = panelEl.querySelector('#assistant-status-label');
  const suggestionsEl = panelEl.querySelector('#assistant-suggestions');
  const input = panelEl.querySelector('#assistant-input');
  const sendBtn = panelEl.querySelector('#assistant-send');
  const messagesEl = panelEl.querySelector('#assistant-messages');

  statusLabel.textContent = statusSummaryLabel(statusInfo);
  statusLabel.className = `assistant-panel__status${statusInfo?.available ? ' is-online' : statusInfo ? ' is-offline' : ''}`;

  if (statusInfo && !statusInfo.available) {
    messagesEl.innerHTML = '';
    messagesEl.appendChild(offlineStateEl());
    suggestionsEl.hidden = true;
    suggestionsEl.innerHTML = '';
    input.disabled = true;
    sendBtn.disabled = true;
    return;
  }

  input.disabled = false;
  sendBtn.disabled = sending;
  renderMessages();

  if (messages.length === 0) {
    suggestionsEl.hidden = false;
    suggestionsEl.innerHTML = SUGGESTIONS.map(
      (s) => `<button type="button" class="assistant-suggestion-chip" data-suggestion="${escapeHtml(s)}">${escapeHtml(s)}</button>`
    ).join('');
    suggestionsEl.querySelectorAll('[data-suggestion]').forEach((btn) => {
      btn.addEventListener('click', () => sendMessage(btn.dataset.suggestion));
    });
  } else {
    suggestionsEl.hidden = true;
    suggestionsEl.innerHTML = '';
  }
}

async function refreshStatus() {
  try {
    statusInfo = await getAssistantStatus();
  } catch {
    statusInfo = { mode: 'unknown', available: false, cloud: { available: false, model: '' }, local: { available: false, model: '' } };
  }
  render();
}

async function sendMessage(rawText, opts = {}) {
  const text = (rawText || '').trim();
  if (!text || sending || !statusInfo?.available) return;

  // Last 6 turns of prior conversation, oldest first — sent alongside the
  // new message so the model has short-term context (see the system prompt
  // for why it still must answer only from CONTEXT, not from this history).
  const history = messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .slice(-6)
    .map((m) => ({ role: m.role, content: m.text }));

  messages.push({ id: ++msgIdCounter, role: 'user', text: opts.displayText || text });
  sending = true;
  render();

  try {
    const payload = { message: text, history, provider: getLlmProviderPreference() };
    const district = opts.district || state.district;
    if (district) payload.district = district;
    if (opts.predictionContext) payload.prediction_context = opts.predictionContext;

    const result = await assistantChat(payload);
    messages.push({
      id: ++msgIdCounter,
      role: 'assistant',
      text: result.reply,
      contextUsed: result.context_used,
      providerUsed: result.provider_used,
      model: result.model,
    });
  } catch (err) {
    messages.push({ id: ++msgIdCounter, role: 'error', text: err.message || 'Something went wrong. Please try again.' });
  } finally {
    sending = false;
    render();
  }
}

function onKeydown(e) {
  if (e.key === 'Escape') closePanel();
}

function openPanel() {
  isOpen = true;
  panelEl.hidden = false;
  scrimEl.hidden = false;
  document.addEventListener('keydown', onKeydown);
  refreshStatus();
  setTimeout(() => panelEl.querySelector('#assistant-input')?.focus(), 50);
}

function closePanel() {
  isOpen = false;
  panelEl.hidden = true;
  scrimEl.hidden = true;
  document.removeEventListener('keydown', onKeydown);
}

function buildFab() {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'assistant-fab';
  btn.setAttribute('aria-label', 'Open LEHAR Assistant');
  btn.innerHTML = ICONS.chat;
  btn.addEventListener('click', () => (isOpen ? closePanel() : openPanel()));
  document.body.appendChild(btn);
  return btn;
}

function buildPanel() {
  scrimEl = document.createElement('div');
  scrimEl.className = 'assistant-scrim';
  scrimEl.hidden = true;
  scrimEl.addEventListener('click', closePanel);

  panelEl = document.createElement('aside');
  panelEl.className = 'assistant-panel';
  panelEl.hidden = true;
  panelEl.setAttribute('role', 'dialog');
  panelEl.setAttribute('aria-label', 'LEHAR Assistant');
  panelEl.innerHTML = `
    <div class="assistant-panel__header">
      <div class="assistant-panel__title">${ICONS.chat}<span>LEHAR Assistant</span></div>
      <span class="assistant-panel__status" id="assistant-status-label">Checking…</span>
      <button type="button" class="btn btn--icon btn--ghost" id="assistant-close" aria-label="Close assistant">${ICONS.close}</button>
    </div>
    <div class="assistant-panel__messages" id="assistant-messages"></div>
    <div class="assistant-suggestions" id="assistant-suggestions"></div>
    <form class="assistant-panel__input-row" id="assistant-form" novalidate>
      <input class="input" type="text" id="assistant-input" placeholder="Ask about weather, irrigation, flood risk…" autocomplete="off" />
      <button type="submit" class="btn btn--primary btn--icon" id="assistant-send" aria-label="Send message">${ICONS.send}</button>
    </form>
    <div class="assistant-panel__footer">AI-generated — not agronomic advice. Answers are grounded only in real app data.</div>
  `;

  document.body.appendChild(scrimEl);
  document.body.appendChild(panelEl);

  panelEl.querySelector('#assistant-close').addEventListener('click', closePanel);
  panelEl.querySelector('#assistant-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const input = panelEl.querySelector('#assistant-input');
    const text = input.value;
    input.value = '';
    sendMessage(text);
  });

  render();
}

/** Call once at app boot — builds the floating button + panel (hidden) and
 * does an initial status check. Safe to call more than once (no-op after
 * the first call). */
export function initAssistant() {
  if (initialized) return;
  initialized = true;
  fabEl = buildFab();
  buildPanel();
  refreshStatus();
}

export function openAssistantPanel() {
  initAssistant();
  openPanel();
}

/** Predict page's "Explain in Urdu" button: opens the panel and sends a
 * fixed instruction with that exact prediction result attached as real
 * CONTEXT data (see AssistantChatRequest.prediction_context) — works for
 * anonymous predictions too, since it doesn't rely on prediction_logs. */
export function explainPredictionInUrdu(result) {
  initAssistant();
  openPanel();
  sendMessage('Explain this irrigation prediction result in simple Urdu.', {
    displayText: 'Explain in Urdu 🗣️',
    district: result?.inputs_used?.district,
    predictionContext: result,
  });
}
