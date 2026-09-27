const EDGE_TRIMMABLE = /[\s\u0085\u200b\u200c\u200d\u2060\ufeff]/u;

export function normalizeSecret(value) {
  const secret = String(value ?? '');
  let start = 0;
  let end = secret.length;
  while (start < end && EDGE_TRIMMABLE.test(secret[start])) start += 1;
  while (end > start && EDGE_TRIMMABLE.test(secret[end - 1])) end -= 1;
  return secret.slice(start, end);
}
