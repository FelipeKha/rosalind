import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useLockProfile } from "@/lib/queries";
import { errorMessage } from "@/lib/tauri";

export function UnlockedScreen({ profileName }: { profileName: string }) {
  const lock = useLockProfile();

  async function onLock() {
    try {
      await lock.mutateAsync();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Welcome back, {profileName}</CardTitle>
        <CardDescription>Your vault is unlocked.</CardDescription>
      </CardHeader>
      <CardContent className="flex justify-center">
        <Button variant="outline" onClick={onLock} disabled={lock.isPending}>
          {lock.isPending ? "Locking…" : "Lock vault"}
        </Button>
      </CardContent>
    </Card>
  );
}
