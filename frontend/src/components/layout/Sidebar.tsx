import { NavLink } from "react-router-dom";

const LINK_BASE =
  "block rounded-lg px-3 py-2 text-sm transition-colors";

function linkClassName({ isActive }: { isActive: boolean }): string {
  return isActive
    ? `${LINK_BASE} bg-slate-800 text-slate-100 font-medium`
    : `${LINK_BASE} text-slate-400 hover:bg-slate-800/50 hover:text-slate-200`;
}

export function Sidebar() {
  return (
    <aside className="w-64 border-r border-slate-800 bg-slate-900 p-6">
      <nav className="space-y-1">
        <NavLink to="/" end className={linkClassName}>
          Dashboard
        </NavLink>

        <NavLink to="/nodes" className={linkClassName}>
          Nodes
        </NavLink>

        <NavLink to="/jobs" className={linkClassName}>
          Jobs
        </NavLink>
      </nav>
    </aside>
  );
}
