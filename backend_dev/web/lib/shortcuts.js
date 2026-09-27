export function toBinding(event) {
  const key = event.key;
  let name = null;
  if (/^F(?:[1-9]|1\d|2[0-4])$/i.test(key)) name = key.toLowerCase();
  else if (/^Key[A-Z]$/.test(event.code)) name = event.code.slice(3).toLowerCase();
  else if (/^Digit[0-9]$/.test(event.code)) name = event.code.slice(5);
  else {
    const named = {
      ' ': 'space', Space: 'space', Escape: 'escape', Tab: 'tab', Enter: 'enter',
      Backspace: 'backspace', Delete: 'delete', Insert: 'insert', Home: 'home', End: 'end',
      PageUp: 'page_up', PageDown: 'page_down', ArrowUp: 'up', ArrowDown: 'down',
      ArrowLeft: 'left', ArrowRight: 'right', Pause: 'pause', ScrollLock: 'scroll_lock',
    };
    name = named[key] ?? null;
  }
  if (!name) return null;
  const modifiers = [event.ctrlKey && 'ctrl', event.altKey && 'alt', event.shiftKey && 'shift', event.metaKey && 'win'].filter(Boolean);
  return [...modifiers, name].join('+');
}

export function formatBinding(text) {
  return String(text ?? '').split('+').map((part) => {
    if (/^f\d+$/i.test(part)) return part.toUpperCase();
    if (part.toLowerCase() === 'page_up') return 'Page Up';
    if (part.toLowerCase() === 'page_down') return 'Page Down';
    if (part.toLowerCase() === 'scroll_lock') return 'Scroll Lock';
    return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
  }).join(' + ');
}
