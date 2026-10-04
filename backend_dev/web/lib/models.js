// Model picker view logic: options per role from the live catalog, and the status badge.
export function pickerOptions(role, catalog, currentId) {
  const models = catalog?.[role]?.models ?? [];
  const list = models.some((model) => model.model_id === currentId) || !currentId ? models : [{ model_id: currentId, display_name: currentId }, ...models];
  return list.map((model) => {
    let label = model.display_name || model.model_id;
    if (model.missing) label += ' — no longer offered';
    else if (role === 'cleanup' && catalog?.cleanup?.provider !== 'nvidia' && model.loaded === false) label += ' — not loaded';
    return { value: model.model_id, label, selected: model.model_id === currentId };
  });
}
export function catalogNote(role, catalog, provider = catalog?.[role]?.provider ?? 'lmstudio') {
  if (!catalog) return 'Loading the model list…';
  const entry = catalog[role];
  if (role === 'cleanup' && provider === 'nvidia') {
    if (entry?.error_code === 'nvidia_api_key_missing') return 'Save an NVIDIA API key to list available models.';
    if (entry?.error_code === 'nvidia_api_key_invalid') return 'The NVIDIA API key was rejected. Check it in Models.';
    if (entry?.error_code) return 'Couldn’t reach NVIDIA to list models.';
    return `${entry?.models?.filter((model) => !model.missing).length ?? 0} available on NVIDIA`;
  }
  if (entry?.error_code) return role === 'cleanup' ? 'Couldn’t read models from LM Studio — is it running?' : 'Couldn’t reach OpenRouter to list models.';
  const count = entry?.models?.length ?? 0;
  return role === 'cleanup' ? `${count} downloaded in LM Studio` : `${count} available on OpenRouter`;
}
export function modelBadge(model, messageFor, provider = 'lmstudio') {
  if (!model) return { tone: 'warning', text: 'Checking' };
  if (model.ready) return { tone: 'success', text: provider === 'nvidia' ? 'Key saved' : 'Ready' };
  return { tone: model.error_code === 'model_loading' ? 'warning' : 'danger', text: messageFor(model.error_code) };
}

export function sameModelOrder(left, right) {
  return Array.isArray(left) && Array.isArray(right) && left.length === right.length && left.every((id, index) => id === right[index]);
}

export function normalizeModelOrder(ids) {
  return ids.map((id) => String(id).trim());
}

export function modelOrderIssue(ids) {
  if (!Array.isArray(ids) || ids.length === 0) return 'Add at least one model.';
  if (ids.length > 12) return 'Use at most 12 models.';
  const normalized = normalizeModelOrder(ids);
  if (normalized.some((id) => !id)) return 'Enter a model ID for every step.';
  if (normalized.some((id) => /\s/u.test(id))) return 'Model IDs cannot contain spaces.';
  if (normalized.some((id) => id.length > 200 || id.includes('..') || !/^[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(id))) return 'Use a model ID like vendor/model-name.';
  if (new Set(normalized).size !== normalized.length) return 'Each model can appear only once.';
  return '';
}

export function moveModelOrder(ids, index, direction) {
  const next = [...ids];
  const destination = index + direction;
  if (!Number.isInteger(index) || ![-1, 1].includes(direction) || index < 0 || index >= next.length || destination < 0 || destination >= next.length) return next;
  [next[index], next[destination]] = [next[destination], next[index]];
  return next;
}

// Fresh snapshots update a clean draft; asynchronous model events preserve edits.
export function syncModelOrderDraft(draft, previousSaved, saved) {
  return [...(draft === null || sameModelOrder(draft, previousSaved) ? saved : draft)];
}
