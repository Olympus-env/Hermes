export type UserProfile = {
  firstName: string;
  lastName: string;
  email: string;
};

const STORAGE_KEY = "hermes.userProfile";

export function loadUserProfile(): UserProfile | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    const data = JSON.parse(raw) as Partial<UserProfile>;
    if (!data.firstName?.trim() || !data.lastName?.trim()) return null;

    return {
      firstName: data.firstName.trim(),
      lastName: data.lastName.trim(),
      email: data.email?.trim() ?? "",
    };
  } catch {
    return null;
  }
}

export function saveUserProfile(profile: UserProfile): UserProfile {
  const normalized = {
    firstName: profile.firstName.trim(),
    lastName: profile.lastName.trim(),
    email: profile.email.trim(),
  };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  return normalized;
}

export function getProfileDisplayName(profile: UserProfile): string {
  const firstInitial = profile.firstName.trim().charAt(0).toLocaleUpperCase("fr-FR");
  return `${firstInitial}. ${profile.lastName.trim()}`;
}

export function getProfileAvatarLetter(profile: UserProfile): string {
  return profile.lastName.trim().charAt(0).toLocaleUpperCase("fr-FR") || "?";
}

export function getHermionUserContext(profile: UserProfile): string {
  return [
    `Utilisateur: ${profile.firstName} ${profile.lastName}`,
    profile.email ? `Email: ${profile.email}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}
