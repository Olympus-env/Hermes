export type UserProfile = {
  firstName: string;
  lastName: string;
  email: string;
  /** Nom de l'entreprise / structure répondant aux AO. */
  entreprise: string;
  /** Activité principale : « ESN Java », « cabinet conseil AMO », « architecte »… */
  activite: string;
  /**
   * Informations libres réinjectées dans les prompts IA (KRINOS + HERMION) :
   * références clients, certifications, périmètre, taille équipe, etc.
   * Plus c'est précis, mieux HERMION rédige.
   */
  infosUtiles: string;
};

const STORAGE_KEY = "hermes.userProfile";
const ONBOARDING_DONE_KEY = "hermes.onboardingDone";

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
      entreprise: data.entreprise?.trim() ?? "",
      activite: data.activite?.trim() ?? "",
      infosUtiles: data.infosUtiles?.trim() ?? "",
    };
  } catch {
    return null;
  }
}

export function saveUserProfile(profile: UserProfile): UserProfile {
  const normalized: UserProfile = {
    firstName: profile.firstName.trim(),
    lastName: profile.lastName.trim(),
    email: profile.email.trim(),
    entreprise: profile.entreprise.trim(),
    activite: profile.activite.trim(),
    infosUtiles: profile.infosUtiles.trim(),
  };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  return normalized;
}

export function isOnboardingDone(): boolean {
  return window.localStorage.getItem(ONBOARDING_DONE_KEY) === "1";
}

export function markOnboardingDone(): void {
  window.localStorage.setItem(ONBOARDING_DONE_KEY, "1");
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
    profile.entreprise ? `Entreprise: ${profile.entreprise}` : "",
    profile.activite ? `Activité: ${profile.activite}` : "",
    profile.infosUtiles ? `Infos: ${profile.infosUtiles}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}
