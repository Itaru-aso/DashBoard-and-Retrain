import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "@/layouts/AppLayout";
import ColorMaster from "@/pages/ColorMaster";
import Dashboard from "@/pages/Dashboard";
import EdgePc from "@/pages/EdgePc";
import Retraining from "@/pages/Retraining";
import TaskList from "@/pages/TaskList";
import ThresholdManagement from "@/pages/ThresholdManagement";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/tasks" element={<TaskList />} />
        <Route path="/colors" element={<ColorMaster />} />
        <Route path="/thresholds" element={<ThresholdManagement />} />
        <Route path="/edge-pcs" element={<EdgePc />} />
        <Route path="/retraining" element={<Retraining />} />
      </Route>
    </Routes>
  );
}
