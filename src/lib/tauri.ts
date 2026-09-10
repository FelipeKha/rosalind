import { invoke } from "@tauri-apps/api/core";

export interface ProfileSummary {
  profile_id: string;
  profile_name: string;
  created_at: number;
}

export interface CreateProfileResult {
  profile: ProfileSummary;
  recovery_phrase: string;
}

export interface SessionInfo {
  locked: boolean;
  profile_id: string | null;
  profile_name: string | null;
}

export interface AuthErrorShape {
  code?: string;
  message?: string;
}

export function errorMessage(err: unknown): string {
  if (typeof err === "string") return err;
  if (err && typeof err === "object") {
    const e = err as AuthErrorShape;
    if (e.message) return e.message;
    if (e.code) return e.code;
  }
  return "Something went wrong";
}

export const listProfiles = () => invoke<ProfileSummary[]>("list_profiles");

export const createProfile = (name: string, passphrase: string) =>
  invoke<CreateProfileResult>("create_profile", { name, passphrase });

export const unlockProfile = (profileId: string, passphrase: string) =>
  invoke<ProfileSummary>("unlock_profile", { profileId, passphrase });

export const lockProfile = () => invoke<void>("lock_profile");

export const resetPassphrase = (
  profileId: string,
  recoveryPhrase: string,
  newPassphrase: string,
) =>
  invoke<void>("reset_passphrase", { profileId, recoveryPhrase, newPassphrase });

export const getSession = () => invoke<SessionInfo>("get_session");
