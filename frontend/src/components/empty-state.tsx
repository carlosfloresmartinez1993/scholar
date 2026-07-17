import type { LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export function EmptyState({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <Card className="rounded-md">
      <CardContent className="flex flex-col items-center gap-1 py-16 text-center">
        <div
          className="stagger-item mb-3 flex size-16 items-center justify-center rounded-md bg-primary/15"
          aria-hidden="true"
        >
          <Icon className="size-8 text-foreground/70" />
        </div>
        <h2 className="stagger-item text-xl" style={{ "--stagger-i": 1 } as React.CSSProperties}>
          {title}
        </h2>
        <p
          className="stagger-item max-w-md text-sm text-muted-foreground"
          style={{ "--stagger-i": 2 } as React.CSSProperties}
        >
          {description}
        </p>
        {children && (
          <div
            className="stagger-item mt-4 flex flex-wrap justify-center gap-2"
            style={{ "--stagger-i": 3 } as React.CSSProperties}
          >
            {children}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
