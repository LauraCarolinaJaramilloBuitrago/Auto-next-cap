// Cliente de la API local. El token llega en la URL (?t=...) y se recuerda.
const params = new URLSearchParams(location.search);
const fromUrl = params.get("t");
if (fromUrl) {
  try { localStorage.setItem("autonext.token", fromUrl); } catch {}
}
let token = fromUrl;
if (!token) {
  try { token = localStorage.getItem("autonext.token"); } catch {}
}

async function call(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-Token": token || "" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

export const api = {
  hasToken: () => !!token,
  state: (since) => call("GET", `/api/state?since=${since}`),
  start: (profile, url) => call("POST", "/api/start", { profile, url }),
  stop: () => call("POST", "/api/stop", {}),
  cmd: (name, args = {}) => call("POST", "/api/command", { name, args }),
  profile: (name) => call("POST", "/api/profile", { name }),
  quality: (enabled) => call("POST", "/api/quality", { enabled }),
  account: (profile, user, password) => call("POST", "/api/account", { profile, user, password }),
  deleteAccount: (profile) => call("POST", "/api/account/delete", { profile }),
  limit: (enabled, count) => call("POST", "/api/limit", { enabled, count }),
};

export function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}
