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

// One payment dialog for both call sites (POST /treasury/payments):
//  - Fixed-charge / cobro-libre mode: pass `charge` (a Charge, or null). No dropdown.
//  - Dropdown mode: pass `charges` (open charges). Defaults to the oldest open charge.
// The dialog is dumb: it just registers the payment and calls `onPaid` before
// closing so each site can do its own thing (print a receipt, invalidate, etc.).
export function PaymentDialog({
  student,
  charge,
  charges,
  open,
  onOpenChange,
  onPaid,
}: {
  student: Student;
  charge?: Charge | null;
  charges?: Charge[];
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onPaid?: (payment: Payment) => void;
}) {
  const dropdown = charges !== undefined;
  const [form, setForm] = useState({
    charge_id: NONE,
    amount: charge ? String(charge.balance) : "",
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
          charge_id: dropdown
            ? form.charge_id === NONE
              ? null
              : form.charge_id
            : (charge?.id ?? null),
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
        amount: charge ? String(charge.balance) : "",
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
    if (open && oldestOpen && form.charge_id === NONE && form.amount === "") {
      setForm((f) => ({
        ...f,
        charge_id: oldestOpen.id,
        amount: String(oldestOpen.balance),
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, oldestOpen?.id]);

  const title = dropdown
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
