export type ThemePreference = 'system' | 'dark' | 'light';

export const THEME_STORAGE_KEY = 'openshare-theme';

export function effectiveTheme(preference: ThemePreference, prefersDark: boolean) {
  return preference === 'system' ? (prefersDark ? 'dark' : 'light') : preference;
}

export function applyTheme(preference: ThemePreference) {
  const query = window.matchMedia('(prefers-color-scheme: dark)');
  document.documentElement.dataset.theme = effectiveTheme(preference, query.matches);
  document.documentElement.dataset.themePreference = preference;
  window.localStorage.setItem(THEME_STORAGE_KEY, preference);
}

export function storedTheme(): ThemePreference {
  const value = window.localStorage.getItem(THEME_STORAGE_KEY);
  return value === 'dark' || value === 'light' || value === 'system' ? value : 'system';
}
