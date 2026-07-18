import { useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { api, apiForm, ApiError } from "@/api/client";
import type { UserPublic } from "@/api/types";
import { queryKeys } from "@/api/query-keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/login")({
  component: LoginPage,
});

type Mode = "password" | "code";

function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function finish(user: UserPublic) {
    queryClient.setQueryData(queryKeys.me, user);
    // students land in their portal; staff in the admin shell
    navigate({ to: user.role === "alumno" ? "/portal" : "/" });
  }

  function fail(err: unknown, fallback: string) {
    setError(
      err instanceof ApiError && (err.status === 400 || err.status === 401)
        ? fallback
        : err instanceof ApiError
          ? err.message
          : "Error de conexión",
    );
  }

  async function onSubmitPassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const user = await apiForm<UserPublic>(
        "/auth/login",
        new URLSearchParams({ username: email, password }),
      );
      finish(user);
    } catch (err) {
      fail(err, "Correo o contraseña incorrectos");
    } finally {
      setLoading(false);
    }
  }

  async function onSubmitCode(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (!codeSent) {
        await api("/auth/login-code/request", {
          method: "POST",
          body: JSON.stringify({ email }),
        });
        setCodeSent(true);
      } else {
        const user = await api<UserPublic>("/auth/login-code/verify", {
          method: "POST",
          body: JSON.stringify({ email, code }),
        });
        finish(user);
      }
    } catch (err) {
      fail(
        err,
        codeSent ? "Código incorrecto o expirado" : "No se pudo enviar el código",
      );
    } finally {
      setLoading(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setCode("");
    setCodeSent(false);
  }

  return (
    <div className="grid min-h-svh lg:grid-cols-[1.1fr_1fr]">
      {/* Brand panel — black, oversized display type, yellow accent */}
      <div className="relative flex flex-col justify-between overflow-hidden bg-[#0a0a0a] p-8 text-white lg:p-12">
        <img
          src="/logo-inue-light.svg"
          alt="Instituto Universitario de Ensenada"
          className="stagger-item h-12 w-fit lg:h-14"
        />

        <div className="hidden lg:block">
          <p
            className="stagger-item font-heading text-[clamp(3rem,6vw,5.5rem)] leading-[0.95] tracking-wide"
            style={{ "--stagger-i": 1 } as React.CSSProperties}
          >
            Control
            <br />
            escolar
            <br />
            <span className="text-[#fce004]">integral.</span>
          </p>
          <div
            className="stagger-item mt-8 h-2 w-24 bg-[#fce004]"
            style={{ "--stagger-i": 2 } as React.CSSProperties}
            aria-hidden="true"
          />
          <p
            className="stagger-item mt-6 max-w-sm text-sm leading-relaxed text-white/60"
            style={{ "--stagger-i": 3 } as React.CSSProperties}
          >
            INUE Escolar — alumnos, planes con RVOE, calificaciones,
            asistencias y tesorería del Instituto Universitario de Ensenada.
          </p>
        </div>

        <p className="hidden text-xs text-white/40 lg:block">
          © {new Date().getFullYear()} INUE — uso administrativo interno
        </p>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center p-6 lg:p-12">
        <div className="w-full max-w-sm">
          <h1 className="text-3xl">Iniciar sesión</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Acceso para personal y alumnos.
          </p>

          <div
            role="group"
            aria-label="Método de acceso"
            className="mt-6 flex gap-1 rounded-md border p-1"
          >
            <Button
              type="button"
              size="sm"
              className="flex-1"
              variant={mode === "password" ? "default" : "ghost"}
              aria-pressed={mode === "password"}
              onClick={() => switchMode("password")}
            >
              Contraseña
            </Button>
            <Button
              type="button"
              size="sm"
              className="flex-1"
              variant={mode === "code" ? "default" : "ghost"}
              aria-pressed={mode === "code"}
              onClick={() => switchMode("code")}
            >
              Código por correo
            </Button>
          </div>

          <form
            onSubmit={mode === "password" ? onSubmitPassword : onSubmitCode}
            className="mt-6 grid gap-5"
          >
            <div className="grid gap-2">
              <Label htmlFor="email">Correo electrónico</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="usuario@inue.edu.mx"
                className="h-11"
                disabled={mode === "code" && codeSent}
              />
            </div>

            {mode === "password" && (
              <div className="grid gap-2">
                <Label htmlFor="password">Contraseña</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-11"
                />
              </div>
            )}

            {mode === "code" && codeSent && (
              <div className="grid gap-2">
                <Label htmlFor="code">Código de 6 dígitos</Label>
                <Input
                  id="code"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  autoComplete="one-time-code"
                  required
                  autoFocus
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  placeholder="000000"
                  className="h-11 text-center text-lg tracking-[0.4em]"
                />
                <p className="text-xs text-muted-foreground">
                  Enviamos un código a {email}. Expira en 10 minutos.{" "}
                  <button
                    type="button"
                    className="font-semibold underline"
                    onClick={() => {
                      setCodeSent(false);
                      setCode("");
                    }}
                  >
                    Cambiar correo
                  </button>
                </p>
              </div>
            )}

            <p
              aria-live="polite"
              className="min-h-5 text-sm font-semibold text-destructive"
            >
              {error}
            </p>
            <Button
              type="submit"
              size="lg"
              className="w-full font-bold"
              disabled={loading}
            >
              {loading
                ? "Un momento…"
                : mode === "password"
                  ? "Ingresar"
                  : codeSent
                    ? "Verificar código"
                    : "Enviar código"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
