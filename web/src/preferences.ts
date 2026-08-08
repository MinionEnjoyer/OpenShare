export type FolderDensity = 'comfortable' | 'compact';
export type MotionPreference = 'system' | 'reduced';

export type LibraryPreferences = {
  folderDensity: FolderDensity;
  motion: MotionPreference;
  confirmDeletes: boolean;
};

export const PREFERENCES_STORAGE_KEY = 'openshare-preferences';

export const DEFAULT_PREFERENCES: LibraryPreferences = {
  folderDensity: 'comfortable',
  motion: 'system',
  confirmDeletes: true,
};

export function storedPreferences(): LibraryPreferences {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(PREFERENCES_STORAGE_KEY) || '{}') as Partial<LibraryPreferences>;
    return {
      folderDensity: parsed.folderDensity === 'compact' ? 'compact' : 'comfortable',
      motion: parsed.motion === 'reduced' ? 'reduced' : 'system',
      confirmDeletes: parsed.confirmDeletes !== false,
    };
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

export function applyPreferences(preferences: LibraryPreferences) {
  document.documentElement.dataset.folderDensity = preferences.folderDensity;
  document.documentElement.dataset.motion = preferences.motion;
  window.localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(preferences));
}
