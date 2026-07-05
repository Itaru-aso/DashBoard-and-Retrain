import { Route, Routes } from "react-router-dom";

import ColorMaster from "@/pages/ColorMaster";
import Dashboard from "@/pages/Dashboard";
import EdgePc from "@/pages/EdgePc";
import Retraining from "@/pages/Retraining";
import TaskList from "@/pages/TaskList";
import ThresholdManagement from "@/pages/ThresholdManagement";

function Home() {
  return <h1>shisui app_ver2</h1>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/tasks" element={<TaskList />} />
      <Route path="/colors" element={<ColorMaster />} />
      <Route path="/thresholds" element={<ThresholdManagement />} />
      <Route path="/edge-pcs" element={<EdgePc />} />
      <Route path="/retraining" element={<Retraining />} />
    </Routes>
  );
}
