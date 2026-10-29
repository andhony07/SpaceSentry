/** Tiny class-name joiner (keeps the bundle free of clsx). */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
