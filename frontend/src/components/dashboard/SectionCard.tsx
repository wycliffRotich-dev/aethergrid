import type { ReactNode } from "react";

type Props = {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
};

export function SectionCard({
  title,
  subtitle,
  action,
  children,
}: Props) {
  return (
    <section className="rounded-2xl border border-neutral-700 bg-neutral-800">
      <div className="flex items-start justify-between border-b border-neutral-700 px-6 py-5">
        <div>
          <h2 className="text-xl font-semibold text-neutral-100">
            {title}
          </h2>

          {subtitle && (
            <p className="mt-1 text-sm text-neutral-400">
              {subtitle}
            </p>
          )}
        </div>

        {action}
      </div>

      <div className="p-6">
        {children}
      </div>
    </section>
  );
}
