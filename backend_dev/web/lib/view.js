export function hudState(status) {
  if (status === 'recording') return { color: 'green' };
  if (status === 'processing' || status === 'awaiting_destination') return { color: 'yellow' };
  if (['awaiting_cleanup_choice', 'error', 'uncertain'].includes(status)) return { color: 'red' };
  return { color: 'blue' };
}
export function shouldToastInserted(event) { return event?.name === 'run:state' && event.status === 'done'; }
export function canDiscard(status) { return ['recording', 'processing', 'awaiting_cleanup_choice', 'awaiting_destination'].includes(status); }
export function recoveryButtons(event) {
  const actions = event?.actions ?? [];
  if (['held', 'awaiting_destination'].includes(event?.status)) return actions.filter((action) => action === 'copy');
  return [...actions.filter((action) => ['retry_cleanup', 'use_original', 'copy', 'retry_stt', 'insert'].includes(action)), 'cancel'];
}
