import { NavLink } from "react-router-dom";

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

const navItems: { path: string; label: string; icon: React.ReactNode }[] = [
  { 
    path: "/", 
    label: "Dashboard",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <rect width="7" height="9" x="3" y="3" rx="1"/>
        <rect width="7" height="5" x="14" y="3" rx="1"/>
        <rect width="7" height="9" x="14" y="12" rx="1"/>
        <rect width="7" height="5" x="3" y="16" rx="1"/>
      </svg>
    ),
  },
  { 
    path: "/nodes", 
    label: "Nodes",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <rect width="20" height="8" x="2" y="2" rx="2" ry="2"/>
        <rect width="20" height="8" x="2" y="14" rx="2" ry="2"/>
        <line x1="6" x2="6.01" y1="6" y2="6"/>
        <line x1="6" x2="6.01" y1="18" y2="18"/>
      </svg>
    ),
  },
  { 
    path: "/jobs", 
    label: "Jobs",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>
        <path d="M15 2H9a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1z"/>
        <path d="M12 11h4"/>
        <path d="M12 16h4"/>
        <path d="M8 11h.01"/>
        <path d="M8 16h.01"/>
      </svg>
    ),
  },
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
            {({ isActive }) => (
              <span className={isActive ? 'text-white' : 'text-neutral-500'}>
                {item.icon}
              </span>
            )}
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}