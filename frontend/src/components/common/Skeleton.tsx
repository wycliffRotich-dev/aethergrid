type Props = {
  className?: string;
};

/**
 * Base pulsing placeholder block. Compose with a width/height
 * className to represent whatever real content will replace it
 * once loading resolves (a line of text, a table cell, a card).
 */
export function Skeleton({ className = "" }: Props) {
  return (
    <div
      className={`animate-pulse rounded bg-slate-800 ${className}`}
      aria-hidden="true"
    />
  );
}
