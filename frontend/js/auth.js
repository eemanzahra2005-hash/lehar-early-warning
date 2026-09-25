/**
 * Login / register modal (tabbed). Stores the JWT + username via api.js's
 * setSession on success. All errors surface as inline field text + a toast —
 * never alert().
 */

import { login, register, setSession, ApiError } from './api.js';
import { openModal, toastSuccess, toastError } from './ui.js';

function formTemplate(tab) {
  const isLogin = tab === 'login';
  return `
    <div class="modal__header">
      <h2>${isLogin ? 'Log in' : 'Create account'}</h2>
    </div>
    <div class="auth-tabs">
      <button type="button" class="auth-tabs__btn ${isLogin ? 'is-active' : ''}" data-tab="login">Log in</button>
      <button type="button" class="auth-tabs__btn ${!isLogin ? 'is-active' : ''}" data-tab="register">Register</button>
    </div>
    <form class="modal__body" id="auth-form" novalidate>
      <div class="field">
        <label for="auth-username">Username</label>
        <input class="input" id="auth-username" name="username" autocomplete="username" minlength="3" maxlength="64" required />
        <div class="field-error" data-error-for="username"></div>
      </div>
      <div class="field">
        <label for="auth-password">Password</label>
        <input class="input" id="auth-password" type="password" name="password" autocomplete="${isLogin ? 'current-password' : 'new-password'}" minlength="6" maxlength="128" required />
        <div class="field-hint" ${isLogin ? 'hidden' : ''}>At least 6 characters.</div>
        <div class="field-error" data-error-for="password"></div>
      </div>
      <button type="submit" class="btn btn--primary btn--block">${isLogin ? 'Log in' : 'Create account'}</button>
    </form>
  `;
}

export function openAuthModal(initialTab = 'login', { onSuccess } = {}) {
  let tab = initialTab;
  const body = document.createElement('div');
  body.innerHTML = formTemplate(tab);

  const { close, modal } = openModal(body, { maxWidth: '380px' });

  function wire() {
    modal.querySelectorAll('.auth-tabs__btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        tab = btn.dataset.tab;
        body.innerHTML = formTemplate(tab);
        wire();
      });
    });

    const form = modal.querySelector('#auth-form');
    const usernameInput = modal.querySelector('#auth-username');
    const passwordInput = modal.querySelector('#auth-password');
    const usernameError = modal.querySelector('[data-error-for="username"]');
    const passwordError = modal.querySelector('[data-error-for="password"]');

    passwordInput.addEventListener('input', () => {
      if (tab === 'register' && passwordInput.value && passwordInput.value.length < 6) {
        passwordError.textContent = 'Password must be at least 6 characters.';
      } else {
        passwordError.textContent = '';
      }
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      usernameError.textContent = '';
      passwordError.textContent = '';

      const username = usernameInput.value.trim();
      const password = passwordInput.value;

      if (username.length < 3) {
        usernameError.textContent = 'Username must be at least 3 characters.';
        return;
      }
      if (tab === 'register' && password.length < 6) {
        passwordError.textContent = 'Password must be at least 6 characters.';
        return;
      }

      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.textContent = tab === 'login' ? 'Logging in…' : 'Creating account…';

      try {
        const result = tab === 'login' ? await login(username, password) : await register(username, password, null);
        setSession(result.access_token, result.username, result.refresh_token);
        toastSuccess(tab === 'login' ? `Welcome back, ${result.username}.` : `Account created — welcome, ${result.username}.`);
        close();
        if (onSuccess) onSuccess(result);
      } catch (err) {
        submitBtn.disabled = false;
        submitBtn.textContent = tab === 'login' ? 'Log in' : 'Create account';
        const message = err instanceof ApiError ? err.message : 'Something went wrong.';
        if (err instanceof ApiError && err.status === 409) {
          usernameError.textContent = 'That username is already taken.';
        } else if (err instanceof ApiError && err.status === 401) {
          passwordError.textContent = 'Invalid username or password.';
        } else {
          toastError(message);
        }
      }
    });
  }

  wire();
  return { close };
}
