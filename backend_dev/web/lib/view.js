export function hudState(status) {
  if (status === 'recording') return { color: 'green', animate: true };
  if (status === 'processing' || status === 'awaiting_destination') return { color: 'yellow', animate: false };
  if (['awaiting_cleanup_choice', 'error', 'uncertain'].includes(status)) return { color: 'red', animate: false };
  return { color: 'blue', animate: false };
}
export function shouldToastInserted(event) { return event?.name === 'run:state' && event.status === 'done'; }
export function recoveryButtons(event) {
  const actions = event?.actions ?? [];
  return [...actions.filter((action) => ['retry_cleanup', 'use_original', 'copy', 'retry_stt', 'insert'].includes(action)), 'cancel'];
}
export function waveformActive(runStatus, lastLevelAt, now) { return runStatus === 'recording' && Number.isFinite(lastLevelAt) && now - lastLevelAt < 500; }
