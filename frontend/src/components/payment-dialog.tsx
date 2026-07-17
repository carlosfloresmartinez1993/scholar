import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/api/client";
import type { Charge, Payment, PaymentMethod, Student } from "@/api/types";
import { formatMoney, PAYMENT_METHOD_LABELS } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const NONE = "__none__";

// One payment dialog for all call sites (POST /treasury/payments):
//  - Fixed-charge / cobro-libre mode: pass `charge` (a Charge, or null). No dropdown.
//  - Dropdown mode: pass `charges` (open charges). Defaults to the oldest open charge.
//  - Multi-cobro mode: pass `multiCharges` (the selected charges). One payment /
//    one folio settles all of them, allocated oldest-due-first by the backend.
// The dialog is dumb: it just registers the payment and calls `onPaid` before
// closing so each site can do its own thing (print a receipt, invalidate, etc.).
export function PaymentDialog({
  student,
  charge,
  charges,
  multiCharges,
  open,
  onOpenChange,
  onPaid,
}: {
  student: Student;
  charge?: Charge | null;
  charges?: Charge[];
  multiCharges?: Charge[];
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onPaid?: (payment: Payment) => void;
}) {
  const multi = multiCharges !== undefined && multiCharges.length > 0;
  const dropdown = !multi && charges !== undefined;
  const multiTotal = multi
    ? Math.round(multiCharges.reduce((s, c) => s + c.balance, 0) * 100) / 100
    : 0;
  const [form, setForm] = useState({
    charge_id: NONE,
    amount: multi ? String(multiTotal) : charge ? String(charge.balance) : "",
    method: "efectivo" as PaymentMethod,
    bank_reference: "",
    notes: "",
  });

  const pay = useMutation({
    mutationFn: () =>
      api<Payment>("/treasury/payments", {
        method: "POST",
        body: JSON.stringify({
          student_id: student.id,
          charge_id: multi
            ? null
            : dropdown
              ? form.charge_id === NONE
                ? null
                : form.charge_id
              : (charge?.id ?? null),
          charge_ids: multi ? multiCharges.map((c) => c.id) : null,
          amount: Number(form.amount),
          method: form.method,
          bank_reference: form.bank_reference,
          notes: form.notes,
        }),
      }),
    onSuccess: (payment) => {
      toast.success(`Pago registrado · ${payment.receipt_folio}`);
      onPaid?.(payment);
      onOpenChange(false); // closing resets the form (effect below)
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Error al registrar el pago"),
  });

  // reset when the dialog closes so a dismissed dialog reopens clean (it stays
  // mounted at the alumnos call site; Caja remounts it, so this is harmless there)
  useEffect(() => {
    if (!open) {
      setForm({
        charge_id: NONE,
        amount: multi ? String(multiTotal) : charge ? String(charge.balance) : "",
        method: "efectivo",
        bank_reference: "",
        notes: "",
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const openCharges = (charges ?? []).filter(
    (c) => c.status === "pendiente" || c.status === "parcial",
  );
  const oldestOpen = openCharges.length
    ? [...openCharges].sort((a, b) => a.due_date.localeCompare(b.due_date))[0]
    : null;
  // default to settling the oldest open charge instead of "sin cargo"
  useEffect(() => {
    if (open && dropdown && oldestOpen && form.charge_id === NONE && form.amount === "") {
      setForm((f) => ({
        ...f,
        charge_id: oldestOpen.id,
        amount: String(oldestOpen.balance),
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, oldestOpen?.id]);

  const title = multi
    ? `Cobrar ${multiCharges.length} cargos`
    : dropdown
      ? "Registrar pago"
      : charge
        ? `Cobrar: ${charge.description}`
        : "Cobro libre";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            pay.mutate();
          }}
        >
          {multi && (
            <div className="rounded-md border">
              {multiCharges.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between gap-3 border-b px-3 py-2 text-sm last:border-b-0"
                >
                  <span className="font-semibold">{c.description}</span>
                  <span data-numeric>{formatMoney(c.balance)}</span>
                </div>
              ))}
              <div className="flex items-center justify-between gap-3 bg-muted/50 px-3 py-2 text-sm font-bold">
                <span>Total</span>
                <span data-numeric>{formatMoney(multiTotal)}</span>
              </div>
            </div>
          )}
          {multi && Number(form.amount) < multiTotal && (
            <p className="text-xs text-muted-foreground">
              Pago parcial: se abona a los cargos más antiguos primero.
            </p>
          )}
          {dropdown && (
            <div className="grid gap-2">
              <Label>Cargo (opcional)</Label>
              <Select
                value={form.charge_id}
                onValueChange={(v) => {
                  const c = openCharges.find((x) => x.id === v);
                  setForm({
                    ...form,
                    charge_id: v,
                    amount: v !== NONE && c ? String(c.balance) : form.amount,
                  });
                }}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Pago a cuenta (sin cargo)</SelectItem>
                  {openCharges.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.description} · saldo {formatMoney(c.balance)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="p-amount">Importe</Label>
              <Input
                id="p-amount"
                type="number"
                min={0.01}
                step="0.01"
                required
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label>Método</Label>
              <Select
                value={form.method}
                onValueChange={(v) => setForm({ ...form, method: v as PaymentMethod })}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(PAYMENT_METHOD_LABELS) as PaymentMethod[]).map((m) => (
                    <SelectItem key={m} value={m}>
                      {PAYMENT_METHOD_LABELS[m]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="p-ref">Referencia bancaria (opcional)</Label>
            <Input
              id="p-ref"
              value={form.bank_reference}
              onChange={(e) => setForm({ ...form, bank_reference: e.target.value })}
              placeholder="SPEI / folio de transferencia"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="p-notes">Observaciones (opcional)</Label>
            <Textarea
              id="p-notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </div>
          <DialogFooter>
            <Button type="submit" className="font-bold" disabled={pay.isPending}>
              {pay.isPending ? "Registrando…" : "Registrar pago e imprimir"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
