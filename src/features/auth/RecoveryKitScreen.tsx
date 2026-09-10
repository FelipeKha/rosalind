import { useState } from "react";
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

const CHECK_INDICES = [2, 10, 18];

export function RecoveryKitScreen({
  phrase,
  onDone,
}: {
  phrase: string;
  onDone: () => void;
}) {
  const words = phrase.trim().split(/\s+/);
  const [answers, setAnswers] = useState<string[]>(["", "", ""]);
  const [confirmed, setConfirmed] = useState(false);

  function check() {
    const valid = CHECK_INDICES.every(
      (idx, i) => answers[i].trim().toLowerCase() === words[idx],
    );
    if (!valid) {
      toast.error("One or more words are incorrect. Please check your kit.");
      return;
    }
    setConfirmed(true);
  }

  return (
    <Card className="w-full max-w-lg">
      <CardHeader>
        <CardTitle>Save your recovery kit</CardTitle>
        <CardDescription>
          These 24 words can recover your data if you forget your passphrase.
          Write them down and store them somewhere safe. Never share them.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-3 gap-2 rounded-md border bg-muted/40 p-3">
          {words.map((word, i) => (
            <div
              key={i}
              className="flex items-center gap-1.5 text-sm font-mono"
            >
              <span className="text-muted-foreground tabular-nums">
                {i + 1}.
              </span>
              <span>{word}</span>
            </div>
          ))}
        </div>

        {!confirmed ? (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              Verify you saved your kit by entering the requested words:
            </p>
            {CHECK_INDICES.map((idx, i) => (
              <div key={idx} className="flex flex-col gap-2">
                <Label htmlFor={`word-${idx}`}>
                  Enter word #{idx + 1}
                </Label>
                <Input
                  id={`word-${idx}`}
                  value={answers[i]}
                  onChange={(e) => {
                    const next = [...answers];
                    next[i] = e.target.value;
                    setAnswers(next);
                  }}
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
            ))}
            <Button type="button" onClick={check}>
              Verify
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-emerald-600">
              Recovery kit verified. Keep it safe.
            </p>
            <Button type="button" onClick={onDone}>
              Continue
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
