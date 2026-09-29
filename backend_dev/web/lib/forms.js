export function termSaveEnabled(spelling) { return typeof spelling === 'string' && spelling.trim().length > 0; }
export function instructionsDirty(text, saved) { return text !== (saved ?? ''); }
export function micDeviceId(value) { return value === '' || value === null || value === undefined ? null : Number(value); }
export function micSelection(settings, devices) {
  const saved = settings?.microphone_id;
  const matching = devices.find((device) => String(device.device_id) === String(saved));
  return matching ? String(matching.device_id) : String(devices.find((device) => device.is_default)?.device_id ?? '');
}
export function micTestRunningAfter(command, result, running) {
  if (!result?.ok) return running;
  if (command === 'mic_test_start') return result.data?.started === true;
  if (command === 'mic_test_stop') return false;
  return running;
}
export const MIC_TEST_IDLE_MS = 1500;
export function micTestEnded(lastLevelAt, now) { return now - lastLevelAt >= MIC_TEST_IDLE_MS; }
