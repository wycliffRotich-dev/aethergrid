import type { ReactNode } from "react";

import { CommandPalette } from "../common/CommandPalette";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { useCommandPalette } from "../../hooks/useCommandPalette";

interface ShellProps {
  children: ReactNode;
}

export function Shell({
  children,
}: ShellProps) {
  const { isOpen, close } = useCommandPalette();

  return (
    <div className="min-h-screen bg-slate-950">

      <Header />

      <div className="flex">

        <Sidebar />

        <main className="flex-1 p-8">
          {children}
        </main>

      </div>

      <CommandPalette isOpen={isOpen} onClose={close} />

    </div>
  );
}
