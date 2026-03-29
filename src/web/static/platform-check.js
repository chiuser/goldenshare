'use strict';

let currentToken = '';

function setOutput(id, value) {
  document.getElementById(id).textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

async function callApi(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (currentToken) headers.Authorization = `Bearer ${currentToken}`;
  const response = await fetch(url, { ...options, headers });
  const requestId = response.headers.get('X-Request-ID') || '';
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, requestId, body };
}

document.getElementById('btn-health').addEventListener('click', async () => {
  const result = await callApi('/api/health');
  document.getElementById('health-request-id').textContent = result.requestId ? `request_id=${result.requestId}` : '';
  setOutput('health-output', result);
});

document.getElementById('btn-login').addEventListener('click', async () => {
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;
  const result = await callApi('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (result.ok) currentToken = result.body.token;
  setOutput('login-output', result);
});

document.getElementById('btn-me').addEventListener('click', async () => {
  const result = await callApi('/api/v1/auth/me');
  setOutput('me-output', result);
});

document.getElementById('btn-admin').addEventListener('click', async () => {
  const result = await callApi('/api/v1/admin/ping');
  setOutput('me-output', result);
});
