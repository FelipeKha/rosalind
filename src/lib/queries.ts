import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createProfile,
  getSession,
  listProfiles,
  lockProfile,
  resetPassphrase,
  unlockProfile,
} from "./tauri";

export function useSession() {
  return useQuery({ queryKey: ["session"], queryFn: getSession });
}

export function useProfiles() {
  return useQuery({ queryKey: ["profiles"], queryFn: listProfiles });
}

export function useCreateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, passphrase }: { name: string; passphrase: string }) =>
      createProfile(name, passphrase),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profiles"] });
      qc.invalidateQueries({ queryKey: ["session"] });
    },
  });
}

export function useUnlockProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ profileId, passphrase }: { profileId: string; passphrase: string }) =>
      unlockProfile(profileId, passphrase),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["session"] });
    },
  });
}

export function useLockProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => lockProfile(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["session"] });
    },
  });
}

export function useResetPassphrase() {
  return useMutation({
    mutationFn: ({
      profileId,
      recoveryPhrase,
      newPassphrase,
    }: {
      profileId: string;
      recoveryPhrase: string;
      newPassphrase: string;
    }) => resetPassphrase(profileId, recoveryPhrase, newPassphrase),
  });
}
