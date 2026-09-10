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
import { useCreateProfile } from "@/lib/queries";
import { errorMessage, type CreateProfileResult } from "@/lib/tauri";

const schema = z
  .object({
    name: z
      .string()
      .min(1, "Profile name is required")
      .max(64, "Profile name is too long"),
    passphrase: z.string().min(12, "Passphrase must be at least 12 characters"),
    confirm: z.string(),
  })
  .refine((data) => data.passphrase === data.confirm, {
    message: "Passphrases do not match",
    path: ["confirm"],
  });

type FormValues = z.infer<typeof schema>;

export function CreateProfileScreen({
  onCreated,
}: {
  onCreated: (result: CreateProfileResult) => void;
}) {
  const createProfile = useCreateProfile();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", passphrase: "", confirm: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    try {
      const result = await createProfile.mutateAsync({
        name: values.name.trim(),
        passphrase: values.passphrase,
      });
      onCreated(result);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  });

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Create your profile</CardTitle>
        <CardDescription>
          Your data is encrypted locally with a master passphrase. If you lose
          it and your recovery kit, your data cannot be recovered.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="name">Profile name</Label>
            <Input id="name" placeholder="Alice" {...register("name")} />
            {errors.name && (
              <p className="text-sm text-destructive">{errors.name.message}</p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="passphrase">Master passphrase</Label>
            <Input
              id="passphrase"
              type="password"
              autoComplete="new-password"
              {...register("passphrase")}
            />
            {errors.passphrase && (
              <p className="text-sm text-destructive">
                {errors.passphrase.message}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="confirm">Confirm passphrase</Label>
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

          <Button type="submit" disabled={createProfile.isPending}>
            {createProfile.isPending ? "Creating…" : "Create profile"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
