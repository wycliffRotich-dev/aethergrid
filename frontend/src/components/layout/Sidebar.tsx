import { NavLink } from "react-router-dom";
import { LayoutDashboard, Server, ClipboardList } from "lucide-react";

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

const navItems: { path: string; label: string; icon: React.ReactNode }[] = [
  { path: "/", label: "Dashboard", icon: <LayoutDashboard size={20} color="#9ca3af" /> },
  { path: "/nodes", label: "Nodes", icon: <Server size={20} color="#9ca3af" /> },
  { path: "/jobs", label: "Jobs", icon: <ClipboardList size={20} color="#9ca3af" /> },
];

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  return (
    <aside className={`
      fixed inset-y-0 left-0 z-50 w-56 border-r border-neutral-700 bg-neutral-900 p-4
      transform transition-transform duration-200 ease-in-out
      lg:relative lg:translate-x-0 lg:z-auto
      ${isOpen ? 'translate-x-0' : '-translate-x-full'}
    `}>
      <div className="flex justify-end mb-4 lg:hidden">
        <button
          onClick={onClose}
          className="p-2 text-neutral-400 hover:text-white"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      <nav className="space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            onClick={onClose}
            className={({ isActive }) => `
              w-full text-left px-3 py-2.5 rounded text-sm font-medium transition-colors flex items-center gap-3
              ${isActive
                ? 'bg-neutral-800 text-white'
                : 'text-neutral-400 hover:text-white hover:bg-neutral-800/50'
              }
            `}
          >
            <span className="flex-shrink-0">
              {item.icon}
            </span>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}