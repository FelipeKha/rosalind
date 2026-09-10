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
import { useResetPassphrase } from "@/lib/queries";
import { errorMessage, type ProfileSummary } from "@/lib/tauri";

const schema = z
  .object({
    profileId: z.string().min(1, "Select a profile"),
    recoveryPhrase: z.string().min(1, "Recovery phrase is required"),
    newPassphrase: z.string().min(12, "Passphrase must be at least 12 characters"),
    confirm: z.string(),
  })
  .refine((data) => data.newPassphrase === data.confirm, {
    message: "Passphrases do not match",
    path: ["confirm"],
  });

type FormValues = z.infer<typeof schema>;

export function ResetScreen({
  profiles,
  onBack,
}: {
  profiles: ProfileSummary[];
  onBack: () => void;
}) {
  const reset = useResetPassphrase();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      profileId: profiles.length === 1 ? profiles[0].profile_id : "",
      recoveryPhrase: "",
      newPassphrase: "",
      confirm: "",
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await reset.mutateAsync({
        profileId: values.profileId,
        recoveryPhrase: values.recoveryPhrase,
        newPassphrase: values.newPassphrase,
      });
      toast.success("Passphrase reset. You can now sign in with your new passphrase.");
      onBack();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  });

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Reset passphrase</CardTitle>
        <CardDescription>
          Enter your 24-word recovery kit to set a new master passphrase.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="profileId">Profile</Label>
            <select
              id="profileId"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              {...register("profileId")}
            >
              {profiles.map((p) => (
                <option key={p.profile_id} value={p.profile_id}>
                  {p.profile_name}
                </option>
              ))}
            </select>
            {errors.profileId && (
              <p className="text-sm text-destructive">{errors.profileId.message}</p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="recoveryPhrase">Recovery phrase (24 words)</Label>
            <textarea
              id="recoveryPhrase"
              rows={3}
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              {...register("recoveryPhrase")}
            />
            {errors.recoveryPhrase && (
              <p className="text-sm text-destructive">
                {errors.recoveryPhrase.message}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="newPassphrase">New passphrase</Label>
            <Input
              id="newPassphrase"
              type="password"
              autoComplete="new-password"
              {...register("newPassphrase")}
            />
            {errors.newPassphrase && (
              <p className="text-sm text-destructive">
                {errors.newPassphrase.message}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="confirm">Confirm new passphrase</Label>
            <Input
              id="confirm"
              type="password"
              autoComplete="new-password"
              {...register("confirm")}
            />
            {errors.confirm && (
              <p className="text-sm text-destructive">{errors.confirm.message}</p>
            )}
          </div>

          <Button type="submit" disabled={reset.isPending}>
            {reset.isPending ? "Resetting…" : "Reset passphrase"}
          </Button>

          <Button
            type="button"
            variant="link"
            className="justify-center"
            onClick={onBack}
          >
            Back to sign in
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
