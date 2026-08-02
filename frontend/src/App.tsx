import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/layout/Shell";
import DashboardPage from "./pages/DashboardPage";
import NodesPage from "./pages/NodesPage";
import JobsPage from "./pages/JobsPage";
import JobDetailPage from "./pages/JobDetailPage";
import { useWorkerHeartbeatKeeper } from "./hooks/useWorkerHeartbeatKeeper";

export default function App() {
  useWorkerHeartbeatKeeper();

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/nodes" element={<NodesPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
      </Routes>
    </Shell>
  );
}
