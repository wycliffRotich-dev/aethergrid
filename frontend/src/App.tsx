import { Routes, Route } from "react-router-dom";
import { Shell } from "./components/layout/Shell";
import DashboardPage from "./pages/DashboardPage";
import NodesPage from "./pages/NodesPage";
import JobsPage from "./pages/JobsPage";

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/nodes" element={<NodesPage />} />
        <Route path="/jobs" element={<JobsPage />} />
      </Routes>
    </Shell>
  );
}