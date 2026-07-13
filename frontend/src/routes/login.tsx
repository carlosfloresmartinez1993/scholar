import { useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { apiForm, ApiError } from "@/api/client";
import type { UserPublic } from "@/api/types";
import { queryKeys } from "@/api/query-keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/login")({
  component: LoginPage,
});

function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const user = await apiForm<UserPublic>(
        "/auth/login",
        new URLSearchParams({ username: email, password }),
      );
      queryClient.setQueryData(queryKeys.me, user);
      navigate({ to: "/" });
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Correo o contraseña incorrectos"
          : err instanceof ApiError
            ? err.message
            : "Error de conexión",
      );
    } finally {
      setLoading(false);
    }
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
            Acceso exclusivo para administración académica.
          </p>

          <form onSubmit={onSubmit} className="mt-8 grid gap-5">
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
              />
            </div>
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
              {loading ? "Ingresando…" : "Ingresar"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
