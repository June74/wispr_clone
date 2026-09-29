export function termSaveEnabled(spelling) { return typeof spelling === 'string' && spelling.trim().length > 0; }
export function instructionsDirty(text, saved) { return text !== (saved ?? ''); }
