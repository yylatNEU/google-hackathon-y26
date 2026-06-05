import React from "react";
import { createRoot } from "react-dom/client";
import Home from "./app/page";
import MonitorPage from "./app/monitor/page";
import ExecutivePage from "./app/executive/page";
import HumanEnhancementPage from "./app/human/page";
import StaffTrainingPage from "./app/staff-training/page";
import ExperienceStudioPage from "./app/experience-studio/page";
import VenueProfilePage from "./app/venue-profile/page";
import AccessibilityJourneyPage from "./app/accessibility-journey/page";
import AgentHandshakePage from "./app/agent-handshake/page";
import OpsAgentPage from "./app/ops-agent/page";
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
  : window.location.pathname.startsWith("/staff-training")
    ? StaffTrainingPage
  : window.location.pathname.startsWith("/experience-studio")
    ? ExperienceStudioPage
  : window.location.pathname.startsWith("/venue-profile")
    ? VenueProfilePage
  : window.location.pathname.startsWith("/accessibility-journey")
    ? AccessibilityJourneyPage
  : window.location.pathname.startsWith("/agent-handshake")
    ? AgentHandshakePage
  : window.location.pathname.startsWith("/ops-agent")
    ? OpsAgentPage
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
