import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { useUnlockProfile } from "@/lib/queries";
import { errorMessage, type ProfileSummary } from "@/lib/tauri";

const schema = z.object({
  profileId: z.string().min(1, "Select a profile"),
  passphrase: z.string().min(1, "Passphrase is required"),
});

type FormValues = z.infer<typeof schema>;

export function UnlockScreen({
  profiles,
  onReset,
}: {
  profiles: ProfileSummary[];
  onReset: () => void;
}) {
  const unlock = useUnlockProfile();
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      profileId: profiles.length === 1 ? profiles[0].profile_id : "",
      passphrase: "",
    },
  });

  const selectedId = watch("profileId");

  const onSubmit = handleSubmit(async (values) => {
    try {
      await unlock.mutateAsync({
        profileId: values.profileId,
        passphrase: values.passphrase,
      });
    } catch (err) {
      toast.error(errorMessage(err));
    }
  });

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Unlock your vault</CardTitle>
        <CardDescription>Choose a profile and enter its passphrase.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label>Profile</Label>
            <div className="flex flex-col gap-2">
              {profiles.map((p) => (
                <button
                  type="button"
                  key={p.profile_id}
                  onClick={() => setValue("profileId", p.profile_id, { shouldValidate: true })}
                  className={cn(
                    "flex items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors",
                    selectedId === p.profile_id
                      ? "border-ring bg-accent"
                      : "border-input hover:bg-accent/50",
                  )}
                >
                  <span className="font-medium">{p.profile_name}</span>
                  <span className="text-xs text-muted-foreground">
                    {new Date(p.created_at * 1000).toLocaleDateString()}
                  </span>
                </button>
              ))}
            </div>
            {errors.profileId && (
              <p className="text-sm text-destructive">{errors.profileId.message}</p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="passphrase">Master passphrase</Label>
            <Input
              id="passphrase"
              type="password"
              autoComplete="current-password"
              {...register("passphrase")}
            />
            {errors.passphrase && (
              <p className="text-sm text-destructive">
                {errors.passphrase.message}
              </p>
            )}
          </div>

          <Button type="submit" disabled={unlock.isPending}>
            {unlock.isPending ? "Unlocking…" : "Unlock"}
          </Button>

          <Button
            type="button"
            variant="link"
            className="justify-center"
            onClick={onReset}
          >
            Forgot passphrase? Use recovery kit
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
