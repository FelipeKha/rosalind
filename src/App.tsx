import { useState } from "react";

import { useProfiles, useSession } from "@/lib/queries";
import type { CreateProfileResult } from "@/lib/tauri";
import { CreateProfileScreen } from "@/features/auth/CreateProfileScreen";
import { RecoveryKitScreen } from "@/features/auth/RecoveryKitScreen";
import { ResetScreen } from "@/features/auth/ResetScreen";
import { UnlockScreen } from "@/features/auth/UnlockScreen";
import { UnlockedScreen } from "@/features/auth/UnlockedScreen";

type View = "signin" | "reset";

function App() {
  const session = useSession();
  const profiles = useProfiles();

  const [pendingRecovery, setPendingRecovery] = useState<CreateProfileResult | null>(
    null,
  );
  const [view, setView] = useState<View>("signin");

  if (session.isLoading || profiles.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (pendingRecovery) {
    return (
      <Centered>
        <RecoveryKitScreen
          phrase={pendingRecovery.recovery_phrase}
          onDone={() => setPendingRecovery(null)}
        />
      </Centered>
    );
  }

  if (session.data && !session.data.locked && session.data.profile_name) {
    return (
      <Centered>
        <UnlockedScreen profileName={session.data.profile_name} />
      </Centered>
    );
  }

  const profileList = profiles.data ?? [];

  if (profileList.length === 0) {
    return (
      <Centered>
        <CreateProfileScreen onCreated={setPendingRecovery} />
      </Centered>
    );
  }

  if (view === "reset") {
    return (
      <Centered>
        <ResetScreen profiles={profileList} onBack={() => setView("signin")} />
      </Centered>
    );
  }

  return (
    <Centered>
      <UnlockScreen profiles={profileList} onReset={() => setView("reset")} />
    </Centered>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      {children}
    </div>
  );
}

export default App;
