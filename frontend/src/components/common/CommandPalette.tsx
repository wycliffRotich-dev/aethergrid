import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Server,
  ListChecks,
  Users,
} from "lucide-react";

type CommandItem = {
  id: string;
  label: string;
  path: string;
  icon: typeof LayoutDashboard;
};

const ITEMS: CommandItem[] = [
  { id: "dashboard", label: "Dashboard", path: "/", icon: LayoutDashboard },
  { id: "nodes", label: "Nodes", path: "/nodes", icon: Server },
  { id: "jobs", label: "Jobs", path: "/jobs", icon: ListChecks },
  { id: "workers", label: "Workers", path: "/workers", icon: Users },
];

type Props = {
  isOpen: boolean;
  onClose: () => void;
};

/**
 * Cmd+K / Ctrl+K navigation palette. Scoped to static routes only in
 * this version -- jumping to a specific job or worker record is left
 * to each entity's own list page and its existing table/search, not
 * duplicated here. See the PR description for the reasoning.
 */
export function CommandPalette({ isOpen, onClose }: Props) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();

    if (normalized.length === 0) {
      return ITEMS;
    }

    return ITEMS.filter((item) =>
      item.label.toLowerCase().includes(normalized),
    );
  }, [query]);

  const [previousIsOpen, setPreviousIsOpen] = useState(isOpen);

  if (isOpen !== previousIsOpen) {
    setPreviousIsOpen(isOpen);
    if (isOpen) {
      setQuery("");
      setSelectedIndex(0);
    }
  }

  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus();
    }
  }, [isOpen]);

  const [previousQuery, setPreviousQuery] = useState(query);

  if (query !== previousQuery) {
    setPreviousQuery(query);
    setSelectedIndex(0);
  }

  function selectItem(item: CommandItem) {
    navigate(item.path);
    onClose();
  }

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelectedIndex((current) =>
        Math.min(current + 1, filtered.length - 1),
      );
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelectedIndex((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = filtered[selectedIndex];
      if (item) {
        selectItem(item);
      }
    }
  }

  if (!isOpen) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-32"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Jump to..."
          aria-label="Jump to a page"
          className="w-full border-b border-slate-800 bg-transparent px-4 py-3 text-white placeholder:text-slate-500 focus:outline-none"
        />

        <div className="max-h-72 overflow-y-auto py-2">
          {filtered.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-slate-500">
              No matches.
            </p>
          ) : (
            filtered.map((item, index) => {
              const Icon = item.icon;
              const isSelected = index === selectedIndex;

              return (
                <button
                  key={item.id}
                  onClick={() => selectItem(item)}
                  onMouseEnter={() => setSelectedIndex(index)}
                  className={`flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm ${
                    isSelected
                      ? "bg-slate-800 text-white"
                      : "text-slate-300"
                  }`}
                >
                  <Icon className="h-4 w-4 text-slate-400" />
                  {item.label}
                </button>
              );
            })
          )}
        </div>

        <div className="border-t border-slate-800 px-4 py-2 text-xs text-slate-500">
          {"\u2191\u2193"} navigate {"\u00b7"} Enter select {"\u00b7"} Esc close
        </div>
      </div>
    </div>
  );
}
