/* ── Tournament API Client & Utilities ── */

const API = {
  token: localStorage.getItem("token"),
  user: JSON.parse(localStorage.getItem("user") || "null"),

  isLoggedIn() { return !!this.token; },

  headers() {
    const h = { "Content-Type": "application/json" };
    if (this.token) h["Authorization"] = `Bearer ${this.token}`;
    return h;
  },

  login(token, user) {
    this.token = token;
    this.user = user;
    localStorage.setItem("token", token);
    localStorage.setItem("user", JSON.stringify(user));
  },

  logout() {
    this.token = null;
    this.user = null;
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    window.location.href = "/";
  },

  async get(url) {
    const r = await fetch(url, { headers: this.headers() });
    if (r.status === 401) { this.logout(); return null; }
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async post(url, data) {
    const r = await fetch(url, { method: "POST", headers: this.headers(), body: JSON.stringify(data) });
    if (r.status === 401) { this.logout(); return null; }
    if (r.status === 409) { showToast("Конфликт: данные изменены другим пользователем. Обновите страницу.", true); throw new Error("conflict"); }
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || "Ошибка");
    }
    return r.json();
  },

  async put(url, data) {
    const r = await fetch(url, { method: "PUT", headers: this.headers(), body: JSON.stringify(data) });
    if (r.status === 401) { this.logout(); return null; }
    if (r.status === 409) { showToast("Матч изменён другим пользователем. Обновите страницу.", true); throw new Error("conflict"); }
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || "Ошибка");
    }
    return r.json();
  },

  async del(url) {
    const r = await fetch(url, { method: "DELETE", headers: this.headers() });
    if (r.status === 401) { this.logout(); return null; }
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || "Ошибка");
    }
    return r.json();
  },
};


/* ── Toast ── */
let toastTimer = null;
function showToast(msg, isError = false) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.style.background = isError ? "var(--danger)" : "var(--pitch-dark)";
  el.style.opacity = "1";
  el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.opacity = "0"; setTimeout(() => el.style.display = "none", 300); }, 2500);
}


/* ── Auth UI ── */
function updateAuthUI() {
  const authArea = document.getElementById("auth-area");
  if (!authArea) return;
  if (API.isLoggedIn()) {
    authArea.innerHTML = `
      <span style="font-size:12px;opacity:.8">${API.user.display_name}</span>
      <button class="btn-header" onclick="API.logout()">Выйти</button>
    `;
  } else {
    authArea.innerHTML = `<a href="/login" class="btn-header" style="text-decoration:none">Войти</a>`;
  }
}


/* ── Status helpers ── */
const STATUS_LABELS = { scheduled: "Запл.", played: "Сыгран", postponed: "Перенесён", cancelled: "Отменён" };
const STATUS_CLASS = { scheduled: "badge-pitch", played: "badge-win", postponed: "badge-draw", cancelled: "badge-loss" };

function statusBadge(s) {
  return `<span class="badge ${STATUS_CLASS[s] || ''}">${STATUS_LABELS[s] || s}</span>`;
}

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}
