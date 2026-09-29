export function createStore(snapshot = {}) {
  return {
    settings: snapshot.settings ?? {},
    models: snapshot.models ?? [],
    runs: snapshot.runs ?? [],
    active_run_id: snapshot.active_run_id ?? null,
    history: [],
    dictionary: [],
    microphones: [],
    latestLevel: null,
  };
}

export function applyEvent(state, event) {
  if (!event || typeof event !== 'object') return state;
  if (event.name === 'run:state' || event.name === 'run:recovery') {
    const current = state.runs.find((run) => run.run_id === event.run_id);
    const version = Number(event.version);
    if (current && (event.name === 'run:recovery' ? version < Number(current.version) : version <= Number(current.version))) return state;
    const next = { ...state, runs: [...state.runs] };
    const run = { ...(current ?? {}), ...event };
    delete run.name;
    const index = next.runs.findIndex((item) => item.run_id === event.run_id);
    if (index < 0) next.runs.unshift(run); else next.runs[index] = run;
    if (event.status === 'recording' || event.status === 'processing' || event.status?.startsWith('awaiting_')) next.active_run_id = event.run_id;
    if (['done', 'error', 'uncertain', 'held', 'cancelled'].includes(event.status) && next.active_run_id === event.run_id) next.active_run_id = null;
    return next;
  }
  if (event.name === 'models:status') return { ...state, models: event.models ?? [] };
  if (event.name === 'audio:level') return { ...state, latestLevel: event };
  return state;
}

export function acceptsEvent(state, event) {
  if (!event || typeof event !== 'object' || !['run:state', 'run:recovery'].includes(event.name)) return false;
  const version = Number(event.version);
  if (!Number.isFinite(version)) return false;
  const current = state.runs.find((run) => run.run_id === event.run_id);
  if (!current) return true;
  return event.name === 'run:recovery' ? version >= Number(current.version) : version > Number(current.version);
}
