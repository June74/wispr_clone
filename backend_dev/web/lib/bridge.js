const MUTATING = new Set(['run_start', 'run_stop', 'run_cancel', 'run_recover', 'settings_update', 'models_select', 'dict_add', 'dict_update', 'dict_delete', 'dict_import', 'history_delete', 'history_delete_all', 'history_copy', 'mic_test_start', 'mic_test_stop']);
export function createBridge(windowLike, options = {}) {
  const hostCall = typeof windowLike === 'function' ? windowLike : async (name, payload) => windowLike?.pywebview?.api?.call(name, payload);
  const clock = options.now ?? Date.now;
  const uuid = options.randomUUID ?? (() => globalThis.crypto.randomUUID());
  let token = null;
  let reconnecting = null;
  const available = () => typeof windowLike === 'function' || typeof windowLike?.pywebview?.api?.call === 'function';
  async function reconnect() {
    if (!available()) return { ok: false, data: null, error: 'unknown_command' };
    if (reconnecting) return reconnecting;
    reconnecting = (async () => {
      const result = await hostCall('state_get', {});
      if (result?.ok) token = result.data?.session_token ?? null;
      return result;
    })();
    try { return await reconnecting; } finally { reconnecting = null; }
  }
  async function call(name, payload = {}) {
    if (!available()) return { ok: false, data: null, error: 'unknown_command' };
    if (!token && name !== 'state_get') await reconnect();
    const body = { ...payload };
    if (name !== 'state_get') body.session_token = token;
    if (MUTATING.has(name)) body.deadline = clock() / 1000 + 10;
    if (name === 'run_start') body.request_id = uuid();
    const result = await hostCall(name, body);
    if (result?.error === 'previous_session_token') await reconnect();
    if (name === 'state_get' && result?.ok) token = result.data?.session_token ?? null;
    return result;
  }
  return { available, call, reconnect };
}
