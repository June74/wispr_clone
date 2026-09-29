export function termSaveEnabled(spelling) { return typeof spelling === 'string' && spelling.trim().length > 0; }
export function instructionsDirty(text, saved) { return text !== (saved ?? ''); }
export function micDeviceId(value) { return value === '' || value === null || value === undefined ? null : Number(value); }
export function micSelection(settings, devices) {
  const saved = settings?.microphone_id;
  const matching = devices.find((device) => String(device.device_id) === String(saved));
  return matching ? String(matching.device_id) : String(devices.find((device) => device.is_default)?.device_id ?? '');
}
