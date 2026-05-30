import React from "react";
import { createRoot } from "react-dom/client";
import Home from "./app/page";
import MonitorPage from "./app/monitor/page";
import ExecutivePage from "./app/executive/page";
import HumanEnhancementPage from "./app/human/page";
import LabsPage from "./features/labs/LabsPage";
import "./app/globals.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing #root element.");
}

const Page = window.location.pathname.startsWith("/monitor")
  ? MonitorPage
  : window.location.pathname.startsWith("/human")
    ? HumanEnhancementPage
  : window.location.pathname.startsWith("/executive")
    ? ExecutivePage
  : window.location.pathname.startsWith("/labs")
    ? LabsPage
    : Home;

createRoot(root).render(
  <React.StrictMode>
    <Page />
  </React.StrictMode>
);
