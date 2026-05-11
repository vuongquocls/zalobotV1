import { config } from '../config.js';

function normalize(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
}

export function isHermesInvoked(text: string): boolean {
  const body = normalize(text);
  return config.zalo.botAliases.some(alias => {
    const normalizedAlias = normalize(alias);
    return normalizedAlias.length > 0 && body.includes(normalizedAlias);
  });
}

export function shouldRouteZaloTextToHermes(text: string, threadType: 0 | 1): {
  route: boolean;
  invokedByAlias: boolean;
} {
  const invokedByAlias = isHermesInvoked(text);
  if (threadType === 0) return { route: true, invokedByAlias };
  return { route: invokedByAlias, invokedByAlias };
}

