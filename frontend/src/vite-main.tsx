import { lazy, StrictMode, Suspense, type ComponentType } from "react";
import { createRoot } from "react-dom/client";
import Home from "./app/page";
import "./app/globals.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing #root element.");
}

const MonitorPage = lazy(() => import("./app/monitor/page"));
const ExecutivePage = lazy(() => import("./app/executive/page"));
const HumanEnhancementPage = lazy(() => import("./app/human/page"));
const StaffTrainingPage = lazy(() => import("./app/staff-training/page"));
const ExperienceStudioPage = lazy(() => import("./app/experience-studio/page"));
const VenueProfilePage = lazy(() => import("./app/venue-profile/page"));
const AccessibilityJourneyPage = lazy(() => import("./app/accessibility-journey/page"));
const AgentHandshakePage = lazy(() => import("./app/agent-handshake/page"));
const OpsAgentPage = lazy(() => import("./app/ops-agent/page"));
const LabsPage = lazy(() => import("./features/labs/LabsPage"));

const routes: Array<{ prefix: string; page: ComponentType }> = [
  { prefix: "/monitor", page: MonitorPage },
  { prefix: "/human", page: HumanEnhancementPage },
  { prefix: "/staff-training", page: StaffTrainingPage },
  { prefix: "/experience-studio", page: ExperienceStudioPage },
  { prefix: "/venue-profile", page: VenueProfilePage },
  { prefix: "/accessibility-journey", page: AccessibilityJourneyPage },
  { prefix: "/agent-handshake", page: AgentHandshakePage },
  { prefix: "/ops-agent", page: OpsAgentPage },
  { prefix: "/executive", page: ExecutivePage },
  { prefix: "/labs", page: LabsPage },
];

const Page = routes.find((route) => window.location.pathname.startsWith(route.prefix))?.page ?? Home;

createRoot(root).render(
  <StrictMode>
    <Suspense fallback={<div className="min-h-screen bg-slate-950 p-6 text-sm font-black text-slate-300">Loading ParkPulse surface...</div>}>
      <Page />
    </Suspense>
  </StrictMode>
);
