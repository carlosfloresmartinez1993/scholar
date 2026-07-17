import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BadgeCheck, MailCheck } from "lucide-react";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/query-keys";
import type { UserPosition, UserPublic } from "@/api/types";
import { POSITION_LABELS, ROLE_LABELS } from "@/lib/format";
import { userInitials } from "@/routes/_auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const Route = createFileRoute("/_auth/perfil")({
  component: PerfilPage,
});

const NO_POSITION = "__none__";

function PerfilPage() {
  const { data: me } = useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api<UserPublic>("/auth/me"),
  });

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center gap-4">
        <span className="flex size-14 items-center justify-center rounded-full bg-muted text-xl font-bold">
          {userInitials(me)}
        </span>
        <div>
          <h1 className="text-3xl">Mi perfil</h1>
          <p className="text-sm text-muted-foreground">
            {me?.email}
            {me &&
              ` · ${me.is_superuser ? "Superusuario" : ROLE_LABELS[me.role]}`}
          </p>
        </div>
      </div>

      {me && <ProfileCard me={me} />}
      {me && <RecoveryEmailCard me={me} />}
      <PasswordCard />
    </div>
  );
}

// --- Perfil -------------------------------------------------------------------

function ProfileCard({ me }: { me: UserPublic }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    display_name: me.display_name ?? "",
    email: me.email,
    location: me.location ?? "",
    position: me.position ?? NO_POSITION,
    current_password: "",
  });
  // changing the login email requires re-entering the current password
  const emailChanged = form.email.trim().toLowerCase() !== me.email;

  const save = useMutation({
    mutationFn: () =>
      api<UserPublic>("/users/me/profile", {
        method: "PATCH",
        body: JSON.stringify({
          display_name: form.display_name.trim() || null,
          email: form.email,
          location: form.location.trim() || null,
          position: form.position === NO_POSITION ? null : form.position,
          ...(emailChanged
            ? { current_password: form.current_password }
            : {}),
        }),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.me, data);
      setForm((f) => ({ ...f, current_password: "" }));
      toast.success("Perfil actualizado");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al guardar"),
  });

  return (
    <Card className="rounded-md border shadow-sm">
      <CardContent className="space-y-4 p-6">
        <div>
          <h2 className="text-lg font-bold">Perfil</h2>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Datos personales
          </p>
        </div>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="p-display">Nombre para mostrar</Label>
              <Input
                id="p-display"
                value={form.display_name}
                placeholder={me.full_name}
                maxLength={255}
                onChange={(e) =>
                  setForm({ ...form, display_name: e.target.value })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="p-email">Email</Label>
              <Input
                id="p-email"
                type="email"
                required
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="p-location">Ubicación</Label>
              <Input
                id="p-location"
                value={form.location}
                placeholder="Ensenada, BC"
                maxLength={255}
                onChange={(e) => setForm({ ...form, location: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label>Puesto</Label>
              <Select
                value={form.position}
                onValueChange={(v) => setForm({ ...form, position: v })}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Seleccione un puesto" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_POSITION}>Sin especificar</SelectItem>
                  {(Object.keys(POSITION_LABELS) as UserPosition[]).map((p) => (
                    <SelectItem key={p} value={p}>
                      {POSITION_LABELS[p]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          {emailChanged && (
            <div className="grid gap-2 sm:max-w-xs">
              <Label htmlFor="p-password">
                Contraseña actual (para cambiar el email)
              </Label>
              <Input
                id="p-password"
                type="password"
                autoComplete="current-password"
                required
                value={form.current_password}
                onChange={(e) =>
                  setForm({ ...form, current_password: e.target.value })
                }
              />
            </div>
          )}
          <div>
            <Button type="submit" className="font-bold" disabled={save.isPending}>
              {save.isPending ? "Guardando…" : "Guardar"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

// --- Correo de recuperación ----------------------------------------------------

const RESEND_SECONDS = 60;

function RecoveryEmailCard({ me }: { me: UserPublic }) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState(
    me.pending_recovery_email ?? me.recovery_email ?? "",
  );
  const [code, setCode] = useState("");
  // null = nothing sent this session; a timestamp = when the last code was sent
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);

  useEffect(() => {
    if (sentAt === null) return;
    const tick = () => {
      const left = RESEND_SECONDS - Math.floor((Date.now() - sentAt) / 1000);
      setSecondsLeft(Math.max(0, left));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [sentAt]);

  const request = useMutation({
    mutationFn: () =>
      api("/users/me/recovery-email/request", {
        method: "POST",
        body: JSON.stringify({ email }),
      }),
    onSuccess: () => {
      setSentAt(Date.now());
      setCode("");
      // the candidate now lives in pending_recovery_email server-side
      queryClient.invalidateQueries({ queryKey: queryKeys.me });
      toast.success("Código enviado — revisa tu correo");
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError && e.status === 429
          ? "Espera un minuto antes de solicitar otro código"
          : e instanceof ApiError
            ? e.message
            : "Error al enviar el código",
      ),
  });

  const verify = useMutation({
    mutationFn: () =>
      api<UserPublic>("/users/me/recovery-email/verify", {
        method: "POST",
        body: JSON.stringify({ code }),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.me, data);
      setSentAt(null);
      setCode("");
      toast.success("Correo de recuperación verificado");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al verificar"),
  });

  const pending = me.pending_recovery_email ?? null;
  const showCodeEntry = sentAt !== null || pending !== null;
  // the green badge belongs to the VERIFIED address: it clears as soon as the
  // typed address differs or a new code is in flight
  const verified =
    !!me.recovery_email_verified &&
    sentAt === null &&
    pending === null &&
    email.trim().toLowerCase() === (me.recovery_email ?? "");

  return (
    <Card className="rounded-md border shadow-sm">
      <CardContent className="space-y-4 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold">Correo de recuperación</h2>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Para recuperar el acceso a tu cuenta
            </p>
          </div>
          {verified && (
            <span className="inline-flex items-center gap-1 rounded-sm bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400">
              <BadgeCheck className="size-3.5" /> Verificado
            </span>
          )}
        </div>

        {me.recovery_email_verified && me.recovery_email && !verified && (
          <p className="text-sm text-muted-foreground">
            Correo verificado actual:{" "}
            <span className="font-semibold text-foreground">
              {me.recovery_email}
            </span>{" "}
            <BadgeCheck className="inline size-3.5 text-emerald-600" />
          </p>
        )}

        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            request.mutate();
          }}
        >
          <div className="grid min-w-64 flex-1 gap-2">
            <Label htmlFor="r-email">Correo</Label>
            <Input
              id="r-email"
              type="email"
              required
              value={email}
              placeholder="personal@example.com"
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <Button
            type="submit"
            variant={showCodeEntry ? "outline" : "default"}
            className="font-bold"
            disabled={request.isPending || (sentAt !== null && secondsLeft > 0)}
          >
            {request.isPending
              ? "Enviando…"
              : sentAt !== null
                ? secondsLeft > 0
                  ? `Reenviar código (${secondsLeft}s)`
                  : "Reenviar código"
                : pending !== null
                  ? "Reenviar código"
                  : verified
                    ? "Cambiar correo"
                    : "Enviar código"}
          </Button>
        </form>

        {showCodeEntry && (
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              verify.mutate();
            }}
          >
            {pending && (
              <p className="basis-full text-sm text-muted-foreground">
                Pendiente de verificar:{" "}
                <span className="font-semibold text-foreground">{pending}</span>
              </p>
            )}
            <div className="grid gap-2">
              <Label htmlFor="r-code">Código de 6 dígitos</Label>
              <Input
                id="r-code"
                required
                inputMode="numeric"
                pattern="\d{6}"
                maxLength={6}
                value={code}
                placeholder="123456"
                className="w-36 text-center font-mono text-lg tracking-[0.3em]"
                onChange={(e) =>
                  setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                }
              />
            </div>
            <Button
              type="submit"
              className="font-bold"
              disabled={verify.isPending || code.length !== 6}
            >
              <MailCheck className="size-4" />
              {verify.isPending ? "Verificando…" : "Verificar"}
            </Button>
            <p className="basis-full text-xs text-muted-foreground">
              El código vence en 10 minutos. Revisa también tu carpeta de spam.
            </p>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

// --- Seguridad -----------------------------------------------------------------

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      toast.error("La nueva contraseña y su confirmación no coinciden");
      return;
    }
    setSaving(true);
    try {
      await api("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      toast.success("Contraseña actualizada");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Error al cambiar la contraseña",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="rounded-md border shadow-sm">
      <CardContent className="space-y-4 p-6">
        <div>
          <h2 className="text-lg font-bold">Seguridad</h2>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Cambiar contraseña
          </p>
        </div>
        <form className="grid gap-4" onSubmit={submit}>
          <div className="grid gap-2">
            <Label htmlFor="pw-current">Contraseña actual</Label>
            <Input
              id="pw-current"
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="pw-new">Nueva contraseña</Label>
              <Input
                id="pw-new"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="pw-confirm">Confirmar nueva contraseña</Label>
              <Input
                id="pw-confirm"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>
          </div>
          <div>
            <Button type="submit" className="font-bold" disabled={saving}>
              {saving ? "Guardando…" : "Guardar"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
