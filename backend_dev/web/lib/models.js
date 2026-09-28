// Model picker view logic: options per role from the live catalog, and the status badge.
export function pickerOptions(role, catalog, currentId) {
  const models = catalog?.[role]?.models ?? [];
  const list = models.some((model) => model.model_id === currentId) || !currentId ? models : [{ model_id: currentId, display_name: currentId }, ...models];
  return list.map((model) => {
    let label = model.display_name || model.model_id;
    if (model.missing) label += ' — no longer offered';
    else if (role === 'cleanup' && model.loaded === false) label += ' — not loaded';
    return { value: model.model_id, label, selected: model.model_id === currentId };
  });
}
export function catalogNote(role, catalog) {
  if (!catalog) return 'Loading the model list…';
  const entry = catalog[role];
  if (entry?.error_code) return role === 'cleanup' ? 'Couldn’t read models from LM Studio — is it running?' : 'Couldn’t reach OpenRouter to list models.';
  const count = entry?.models?.length ?? 0;
  return role === 'cleanup' ? `${count} downloaded in LM Studio` : `${count} available on OpenRouter`;
}
export function modelBadge(model, messageFor) {
  if (!model) return { tone: 'warning', text: 'Checking' };
  if (model.ready) return { tone: 'success', text: 'Ready' };
  return { tone: model.error_code === 'model_loading' ? 'warning' : 'danger', text: messageFor(model.error_code) };
}
