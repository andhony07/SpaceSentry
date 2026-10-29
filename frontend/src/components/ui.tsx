import {
  useState,
  useEffect,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import {
  AlertTriangle,
  Check,
  CircleAlert,
  Copy,
  Loader2,
  X,
} from "lucide-react";
import { cn } from "../utils/cx";

/* ---------------------------------------------------------------- Spinner */

export function Spinner({ className, size = 18 }: { className?: string; size?: number }) {
  return (
    <Loader2
      size={size}
      aria-hidden
      className={cn("animate-spin text-sentry-400 shrink-0", className)}
    />
  );
}

export function useToast() {
  const toastFunc = (message: string, { variant }: { variant?: "success" | "error" } = {}) => {
    const el = document.createElement("div");
    el.className = cn(
      "fixed bottom-4 right-4 px-4 py-2.5 rounded-lg text-sm font-medium z-50 shadow-xl border transition-all duration-200 flex items-center gap-2",
      variant === "success"
        ? "bg-emerald-950/90 text-emerald-300 border-emerald-500/40"
        : variant === "error"
          ? "bg-rose-950/90 text-rose-300 border-rose-500/40"
          : "bg-surface-2 text-slate-100 border-slate-700",
    );
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 200);
    }, 2800);
  };
  return { toast: toastFunc };
}

export function LoadingPanel({ label = "Loading…" }: { label?: string }) {
  return (
    <div
      className="flex items-center justify-center gap-3 rounded-xl border border-slate-800/80 bg-surface-1 p-8 text-sm text-slate-300"
      role="status"
    >
      <Spinner size={20} />
      <span>{label}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ Badge */

const BADGE_STYLES: Record<string, string> = {
  queued: "bg-slate-800/80 text-slate-300 ring-slate-700/60",
  running: "bg-sentry-500/15 text-sentry-300 ring-sentry-500/40",
  completed: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40",
  cancelled: "bg-amber-500/15 text-amber-300 ring-amber-500/40",
  failed: "bg-rose-500/15 text-rose-300 ring-rose-500/40",
  potential_cleanup: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40",
  review_required: "bg-amber-500/15 text-amber-300 ring-amber-500/40",
  protected: "bg-rose-500/15 text-rose-300 ring-rose-500/40",
};

export function ScanStatusBadge({ status }: { status: string | null }) {
  const style = (status && BADGE_STYLES[status]) || "bg-slate-800/80 text-slate-400 ring-slate-700/60";
  const isRunning = status === "running" || status === "queued";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium capitalize ring-1 ring-inset",
        style,
      )}
    >
      {isRunning && (
        <span className="relative flex size-1.5">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-sentry-400 opacity-75"></span>
          <span className="relative inline-flex size-1.5 rounded-full bg-sentry-400"></span>
        </span>
      )}
      {status ?? "no scan yet"}
    </span>
  );
}

export function Badge({
  variant = "neutral",
  className,
  children,
}: {
  variant?: "neutral" | "sentry" | "success" | "warning" | "danger";
  className?: string;
  children: ReactNode;
}) {
  const variants = {
    neutral: "bg-slate-800/80 text-slate-300 ring-slate-700/60",
    sentry: "bg-sentry-500/15 text-sentry-300 ring-sentry-500/40",
    success: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40",
    warning: "bg-amber-500/15 text-amber-300 ring-amber-500/40",
    danger: "bg-rose-500/15 text-rose-300 ring-rose-500/40",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset",
        variants[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* -------------------------------------------------------------- Button */

const BTN_BASE =
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sentry-400/80 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none";

const BTN_VARIANTS = {
  primary: "bg-sentry-600 text-white shadow-sm hover:bg-sentry-500 active:bg-sentry-700",
  secondary: "bg-surface-2 text-slate-200 border border-slate-700/60 hover:bg-surface-3 hover:text-white hover:border-slate-600",
  outline: "border border-slate-700/80 bg-surface-1/60 text-slate-300 hover:border-slate-500 hover:bg-surface-2 hover:text-slate-100",
  ghost: "text-slate-300 hover:bg-surface-2 hover:text-slate-100",
  danger: "bg-rose-600/90 text-white hover:bg-rose-600 active:bg-rose-700",
};

const BTN_SIZES = {
  sm: "px-2.5 py-1 text-xs",
  md: "px-3.5 py-1.5 text-sm",
  lg: "px-4.5 py-2.5 text-base",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof BTN_VARIANTS;
  size?: keyof typeof BTN_SIZES;
};

export function Button({
  variant = "outline",
  size = "md",
  className,
  type,
  children,
  ...rest
}: ButtonProps) {
  const resolvedType: "submit" | "button" = type === "submit" ? "submit" : "button";
  return (
    <button
      type={resolvedType}
      className={cn(BTN_BASE, BTN_VARIANTS[variant], BTN_SIZES[size], className)}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------- CopyButton */

export function CopyButton({
  text,
  label = "Copy",
  className,
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={copied ? "Copied to clipboard!" : `${label} path`}
      aria-label={copied ? "Copied" : `${label} path`}
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-slate-400 transition-colors hover:bg-surface-3 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sentry-400",
        copied && "text-emerald-400 hover:text-emerald-300",
        className,
      )}
    >
      {copied ? <Check size={13} aria-hidden /> : <Copy size={13} aria-hidden />}
      <span className="text-[11px]">{copied ? "Copied" : label}</span>
    </button>
  );
}

/* ---------------------------------------------------------------- Inputs */

export function TextInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "w-full rounded-lg border border-slate-700/80 bg-surface-2 px-3.5 py-2 text-sm text-slate-100 placeholder:text-slate-500 transition-colors focus-visible:border-sentry-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sentry-400/30",
        className,
      )}
      {...rest}
    />
  );
}

export function NumberInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <TextInput type="number" className="w-28 font-mono" {...props} />;
}

/* -------------------------------------------------------------- Callouts */

export function ErrorPanel({
  title,
  message,
  onRetry,
}: {
  title: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="mt-6 rounded-xl border border-rose-500/30 bg-rose-950/20 p-5 text-sm"
    >
      <div className="flex items-center gap-2 font-semibold text-rose-300">
        <CircleAlert size={18} aria-hidden /> {title}
      </div>
      {message ? <p className="mt-2 text-slate-300 leading-relaxed">{message}</p> : null}
      {onRetry ? (
        <Button variant="outline" size="sm" className="mt-4 border-rose-500/40 hover:bg-rose-950/30 text-rose-200" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function PartialNotice({ partial }: { partial: boolean }) {
  if (!partial) return null;
  return (
    <div className="inline-flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-950/25 px-3 py-1.5 text-xs font-medium text-amber-300 shadow-sm">
      <AlertTriangle size={14} aria-hidden className="shrink-0 text-amber-400" />
      <span>Partial scan: results reflect files scanned before cancellation.</span>
    </div>
  );
}

export function Callout({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-slate-800/80 bg-surface-1/70 px-4 py-3 text-xs leading-relaxed text-slate-300 flex items-start gap-2.5",
        className,
      )}
    >
      <div className="shrink-0 text-sentry-400 mt-0.5">ℹ</div>
      <div className="grow">{children}</div>
    </div>
  );
}

/* ------------------------------------------------------------- Stat tile */

export function StatTile({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-slate-800/80 bg-surface-1 p-4 shadow-sm transition-colors hover:border-slate-700/80 flex flex-col justify-between",
        hint && "cursor-help",
      )}
      title={hint}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</span>
        {icon && <div className="text-slate-400 shrink-0">{icon}</div>}
      </div>
      <div className="mt-2 font-mono text-xl font-bold tracking-tight text-slate-100">{value}</div>
      {hint && <div className="mt-1 text-[11px] text-slate-500 truncate">{hint}</div>}
    </div>
  );
}

/* ------------------------------------------------------------- EmptyState */

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-slate-800/80 bg-surface-1 p-10 text-center shadow-sm">
      {icon && <div className="mx-auto mb-3 flex size-12 items-center justify-center rounded-xl bg-surface-2 text-slate-400 ring-1 ring-slate-700/60">{icon}</div>}
      <h3 className="text-base font-semibold text-slate-100">{title}</h3>
      <p className="mx-auto mt-1.5 max-w-md text-sm text-slate-400 leading-relaxed">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* --------------------------------------------------------------- Modal */

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  maxWidth = "max-w-2xl",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  maxWidth?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 overflow-y-auto"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={cn(
          "w-full rounded-xl border border-slate-700/80 bg-surface-1 shadow-2xl transition-all my-8",
          maxWidth,
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-slate-800/80 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded-lg p-1 text-slate-400 hover:bg-surface-2 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sentry-400"
          >
            <X size={18} aria-hidden />
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}
