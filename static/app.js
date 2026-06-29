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


/* ── Dark Theme ── */
function initTheme() {
  const saved = localStorage.getItem("theme");
  if (saved === "dark") document.documentElement.setAttribute("data-theme", "dark");
}
function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("theme", next || "light");
  updateAuthUI();
}
initTheme();


/* ── Auth UI ── */
function updateAuthUI() {
  const authArea = document.getElementById("auth-area");
  if (!authArea) return;
  const themeBtn = `<button class="btn-header" onclick="toggleTheme()" title="Тема">${document.documentElement.getAttribute('data-theme')==='dark'?'☀️':'🌙'}</button>`;
  if (API.isLoggedIn()) {
    authArea.innerHTML = `
      <span style="font-size:12px;opacity:.8">${API.user.display_name}</span>
      <button class="btn-header" onclick="showChangePassword()">🔑</button>
      ${themeBtn}
      <button class="btn-header" onclick="API.logout()">Выйти</button>
    `;
  } else {
    authArea.innerHTML = `${themeBtn}<a href="/login" class="btn-header" style="text-decoration:none">Войти</a>`;
  }
}

/* ── Change Password Modal ── */
function showChangePassword() {
  let overlay = document.getElementById("pw-modal");
  if (overlay) { overlay.remove(); }
  overlay = document.createElement("div");
  overlay.id = "pw-modal";
  overlay.className = "modal-overlay";
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  overlay.innerHTML = `
    <div class="modal" onclick="event.stopPropagation()" style="max-width:380px">
      <div class="modal-header">
        <h3>Сменить пароль</h3>
        <button class="modal-close" onclick="document.getElementById('pw-modal').remove()">✕</button>
      </div>
      <div class="modal-body">
        <div id="pw-error" class="hidden" style="background:var(--danger-bg);color:var(--danger);padding:8px 12px;border-radius:6px;font-size:13px;margin-bottom:12px"></div>
        <div class="form-group" style="margin-bottom:12px">
          <label>Текущий пароль</label>
          <input class="input" id="pw-old" type="password">
        </div>
        <div class="form-group" style="margin-bottom:12px">
          <label>Новый пароль</label>
          <input class="input" id="pw-new" type="password">
        </div>
        <div class="form-group" style="margin-bottom:16px">
          <label>Повторите новый пароль</label>
          <input class="input" id="pw-confirm" type="password">
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button class="btn btn-ghost" onclick="document.getElementById('pw-modal').remove()">Отмена</button>
          <button class="btn btn-primary" onclick="doChangePassword()">Сменить</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
}

async function doChangePassword() {
  const oldPw = document.getElementById("pw-old").value;
  const newPw = document.getElementById("pw-new").value;
  const confirm = document.getElementById("pw-confirm").value;
  const errEl = document.getElementById("pw-error");
  errEl.classList.add("hidden");

  if (!oldPw || !newPw) {
    errEl.textContent = "Заполните все поля";
    errEl.classList.remove("hidden"); return;
  }
  if (newPw !== confirm) {
    errEl.textContent = "Пароли не совпадают";
    errEl.classList.remove("hidden"); return;
  }
  if (newPw.length < 4) {
    errEl.textContent = "Минимум 4 символа";
    errEl.classList.remove("hidden"); return;
  }
  try {
    await API.put("/api/users/password", { old_password: oldPw, new_password: newPw });
    document.getElementById("pw-modal").remove();
    showToast("Пароль изменён");
  } catch (e) {
    errEl.textContent = e.message || "Ошибка";
    errEl.classList.remove("hidden");
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
