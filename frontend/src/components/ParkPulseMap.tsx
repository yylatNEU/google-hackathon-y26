"use client";

import { useEffect, useState } from "react";
import type { GuestFlow, ParkPhysicalMap, ParkState } from "@/types/park";
import type { DeliveryDispatch, DemoScenario, OperatorCommandResponse, ProactiveRunTelemetry, RunTelemetry, ScenarioKey, SignalTriageResult } from "@/types/platform";
import { dispatchBody, pct, pressureTone, ratePct, toneClass } from "@/lib/parkPulseDemoContent";
import { sortedByRisk } from "@/lib/parkPulseAgents";
import { ActionBusPanel } from "@/components/ParkPulseActionBus";

export type ZoneKind = "ride" | "food" | "indoor" | "entry" | "shelter";

export const DEFAULT_PHYSICAL_MAP: ParkPhysicalMap = {
  scale: { widthMeters: 820, heightMeters: 540, north: "top" },
  landmarks: [
    { id: "frontGate", name: "Front Gate", type: "entry", x: 120, y: 520, w: 160, h: 50, guestVisible: true },
    { id: "mainStreet", name: "Main Street Shops", type: "retail", x: 245, y: 454, w: 180, h: 56, guestVisible: true },
    { id: "dragonCoaster", name: "Dragon Coaster", type: "coaster", x: 690, y: 145, w: 210, h: 155, guestVisible: true },
    { id: "indoorLaunch", name: "Indoor Launch", type: "indoor_ride", x: 120, y: 88, w: 290, h: 170, guestVisible: true },
    { id: "theaterB", name: "Theater B", type: "show", x: 188, y: 300, w: 220, h: 102, guestVisible: true },
    { id: "paradeRoute", name: "Parade Route", type: "show_route", x: 315, y: 394, w: 260, h: 42, guestVisible: true },
    { id: "arcade", name: "Arcade", type: "arcade", x: 435, y: 312, w: 185, h: 102, guestVisible: true },
    { id: "foodCourtA", name: "Food Court A", type: "food", x: 615, y: 470, w: 190, h: 85, guestVisible: true },
    { id: "serviceYard", name: "Maintenance Yard", type: "backstage", x: 825, y: 52, w: 122, h: 96, guestVisible: false },
    { id: "firstAid", name: "First Aid", type: "medical", x: 486, y: 500, w: 58, h: 42, guestVisible: true },
    { id: "lake", name: "Central Lake", type: "water", x: 660, y: 358, w: 220, h: 140, guestVisible: true },
    { id: "fireworksViewing", name: "Fireworks Viewing", type: "show", x: 620, y: 335, w: 275, h: 66, guestVisible: true },
  ],
  facilities: [
    { id: "restroomEast", name: "Restrooms", type: "restroom", x: 578, y: 438, waitMins: 4 },
    { id: "restroomWest", name: "Restrooms", type: "restroom", x: 152, y: 404, waitMins: 3 },
    { id: "waterNorth", name: "Water refill", type: "water", x: 522, y: 244, waitMins: 2 },
    { id: "lockerFront", name: "Lockers", type: "locker", x: 286, y: 520, waitMins: 6 },
    { id: "guestServices", name: "Guest services", type: "care", x: 204, y: 545, waitMins: 12 },
    { id: "shadeGarden", name: "Shade garden", type: "shade", x: 526, y: 152, waitMins: 0 },
  ],
  supportStations: [
    {
      id: "supportEntry",
      name: "Entry AI Help Desk",
      x: 206,
      y: 500,
      status: "online",
      waitMins: 2,
      agentName: "Mira",
      specialties: ["arrival questions", "lost tickets", "family routes"],
      recommendations: ["Start with Theater B while Dragon Coaster recovers.", "Use Main Street snacks before the food court peak."],
      sampleQuestions: ["Where should my family go first?", "Can you find a calm route to indoor rides?"],
    },
    {
      id: "supportCoaster",
      name: "Thrill Zone Support",
      x: 622,
      y: 300,
      status: "busy",
      waitMins: 5,
      agentName: "Kai",
      specialties: ["ride downtime", "wait alternatives", "guest recovery"],
      recommendations: ["Recommend Arcade Zone for short waits.", "Offer Theater B as a lower-crowd indoor option."],
      sampleQuestions: ["What should I do while Dragon Coaster is down?", "Which nearby ride has the shortest wait?"],
    },
    {
      id: "supportFood",
      name: "Food Court Guide",
      x: 578,
      y: 486,
      status: "online",
      waitMins: 3,
      agentName: "Sol",
      specialties: ["food recommendations", "mobile order help", "dietary questions"],
      recommendations: ["Send mobile orders to Main Street Shops if Food Court A exceeds 15 minutes.", "Recommend water refill before guests join indoor queues."],
      sampleQuestions: ["Where can I eat with the shortest pickup time?", "What snack stop is best before the next show?"],
    },
    {
      id: "supportIndoor",
      name: "Indoor Recommendation Hub",
      x: 404,
      y: 284,
      status: "online",
      waitMins: 1,
      agentName: "Nia",
      specialties: ["indoor routes", "accessibility", "weather shelter"],
      recommendations: ["Route heat-sensitive guests through Covered Plaza.", "Recommend Arcade Zone for flexible groups."],
      sampleQuestions: ["What indoor attraction fits our group?", "How do we avoid the most crowded path?"],
    },
  ],
  queues: [
    { id: "dragonQueue", name: "Dragon Coaster queue", rideId: "dragonCoaster", points: [[650, 242], [612, 272], [665, 307], [733, 310], [790, 288]], guests: 540, waitMins: 44, status: "down", shadePct: 18, spillbackRisk: "critical" },
    { id: "indoorLaunchQueue", name: "Indoor Launch queue", rideId: "indoorLaunch", points: [[170, 260], [210, 285], [278, 282], [354, 266]], guests: 430, waitMins: 55, status: "constrained", shadePct: 82, spillbackRisk: "watch" },
    { id: "foodPickupQueue", name: "Food pickup line", rideId: "foodCourtA", points: [[596, 462], [620, 430], [678, 432], [733, 452]], guests: 116, waitMins: 18, status: "normal", shadePct: 54, spillbackRisk: "watch" },
    { id: "paradeCrossingQueue", name: "Parade crossing hold", rideId: "paradeRoute", points: [[330, 424], [390, 408], [462, 414], [535, 394], [596, 374]], guests: 420, waitMins: 12, status: "constrained", shadePct: 44, spillbackRisk: "critical" },
    { id: "fireworksExitQueue", name: "Fireworks exit wave", rideId: "fireworksViewing", points: [[748, 402], [700, 442], [628, 474], [526, 506], [386, 532], [238, 548]], guests: 180, waitMins: 5, status: "normal", shadePct: 24, spillbackRisk: "normal" },
  ],
  guestGroups: [
    { id: "familyExitDragon", segment: "families leaving Dragon Coaster queue", count: 260, x: 708, y: 300, destination: "Theater B", mood: "frustrated", pace: "slow" },
    { id: "teenThrill", segment: "teen thrill riders", count: 210, x: 820, y: 218, destination: "Sky Drop", mood: "impatient", pace: "fast" },
    { id: "mobileOrder", segment: "mobile order guests", count: 145, x: 674, y: 462, destination: "Food Court A", mood: "neutral", pace: "stopped" },
    { id: "strollerFamilies", segment: "stroller families", count: 118, x: 306, y: 486, destination: "Shade garden", mood: "heat_stress", pace: "slow" },
    { id: "shelterGuests", segment: "guests seeking shelter", count: 160, x: 468, y: 356, destination: "Covered Plaza", mood: "neutral", pace: "medium" },
    { id: "paradeFamilies", segment: "parade viewing families", count: 560, x: 430, y: 410, destination: "Parade Route", mood: "blocked_crossing", pace: "stopped" },
    { id: "fireworksExit", segment: "fireworks exit wave", count: 160, x: 724, y: 414, destination: "Front Gate", mood: "exit_focused", pace: "medium" },
    { id: "showUnload", segment: "show unload guests", count: 95, x: 288, y: 350, destination: "Food Court A", mood: "neutral", pace: "medium" },
    { id: "shortStaffedOps", segment: "staff task cluster", count: 16, x: 558, y: 518, destination: "Food Court A", mood: "normal", pace: "working" },
  ],
  serviceRoutes: [
    { id: "northServiceRoad", name: "North service road", points: [[946, 80], [875, 92], [832, 142], [808, 198]], access: "maintenance_only", blocked: false },
    { id: "foodServiceAlley", name: "Food service alley", points: [[932, 560], [830, 545], [735, 530], [620, 520]], access: "back_of_house", blocked: false },
    { id: "medicalAccess", name: "Medical access lane", points: [[95, 584], [235, 550], [384, 516], [510, 500]], access: "emergency", blocked: false },
  ],
  realismNotes: ["Physical constraints include guest-visible landmarks, backstage routes, queue footprints, facilities, guest group clusters, and timed parade/show/fireworks release waves."],
};

export const ZONE_LAYOUT: Record<string, { x: number; y: number; w: number; h: number; kind: ZoneKind }> = {
  entrancePlaza: { x: 9, y: 63, w: 21, h: 16, kind: "entry" },
  coasterPlaza: { x: 63, y: 11, w: 27, h: 20, kind: "ride" },
  indoorHub: { x: 13, y: 12, w: 28, h: 18, kind: "indoor" },
  arcadeZone: { x: 20, y: 40, w: 22, h: 16, kind: "indoor" },
  foodCourt1: { x: 59, y: 59, w: 25, h: 17, kind: "food" },
  coveredPlaza: { x: 45, y: 37, w: 24, h: 15, kind: "shelter" },
};

export function pointsToPath(points: Array<[number, number]>, close = false) {
  if (!points.length) return "";
  const [first, ...rest] = points;
  return `M${first[0]} ${first[1]} ${rest.map(([x, y]) => `L${x} ${y}`).join(" ")}${close ? " Z" : ""}`;
}

export function landmarkFill(type: string) {
  if (type === "coaster") return "#8f5a3c";
  if (type === "indoor_ride") return "#dfe8e2";
  if (type === "show") return "#4b6473";
  if (type === "show_route") return "#8b5cf6";
  if (type === "arcade") return "#d6b66f";
  if (type === "food") return "#f3ead8";
  if (type === "backstage") return "#777c80";
  if (type === "medical") return "#fdf2f2";
  if (type === "retail") return "#e7d5b6";
  return "#d8cfb8";
}

export function facilityGlyph(type: string) {
  if (type === "restroom") return "WC";
  if (type === "water") return "H2O";
  if (type === "locker") return "LK";
  if (type === "care") return "?";
  if (type === "shade") return "SH";
  return "i";
}

export function supportStationTone(status: string) {
  if (status === "offline") return "#64748b";
  if (status === "busy") return "#f59e0b";
  return "#0891b2";
}

export function groupTone(mood: string) {
  if (["frustrated", "impatient", "confused", "heat_stress", "stretched", "blocked_crossing", "fairness_complaint"].includes(mood)) return "#dc2626";
  if (["watching_weather", "watching_fireworks", "exit_focused", "hungry", "priority_return"].includes(mood)) return "#d97706";
  return "#0f766e";
}

export type MapLayer = "overview" | "attractions" | "queues" | "guests" | "support" | "operations" | "signals";

export type MapSelectionKind = "attraction" | "queue" | "facility" | "guest-group" | "support-station";

export type MapSelection = {
  id: string;
  kind: MapSelectionKind;
  title: string;
  subtitle: string;
  status: string;
  tone: "risk" | "watch" | "ok";
  detail: string;
  waitMins?: number;
  guests?: number;
  actions: string[];
  prompt: string;
};

export type AgentMapGrounding = {
  primary_zone_id?: string | null;
  highlight_zone_ids?: string[];
  landmark_ids?: string[];
  queue_ids?: string[];
  path_ids?: string[];
  receiver_targets?: Array<{ channel?: string; target?: string; status?: string }>;
  focus?: string;
  rationale?: string;
};

export type AgentImpactReplay = {
  status?: string;
  mode?: string;
  created_at?: string;
  horizon_minutes?: number;
  executed?: boolean;
  action_plan?: { id?: string; target?: string; action?: string; label?: string };
  state?: Partial<ParkState>;
  comparison?: {
    before?: Record<string, unknown>;
    actual_after?: Record<string, unknown>;
    shadow_baseline_after?: Record<string, unknown>;
    actual_score?: number;
    baseline_score?: number;
    score_lift?: number;
    impact?: {
      headline?: string;
      guest_minutes_saved?: number;
      wait_minutes_avoided?: number;
      queue_guests_avoided?: number;
      density_points_reduced?: number;
      path_congestion_avoided?: number;
      food_backlog_avoided?: number;
      satisfaction_lift?: number;
    };
  };
  map_delta?: {
    primary_metric?: string;
    wait_minutes_avoided?: number;
    queue_guests_avoided?: number;
    density_points_reduced?: number;
    path_congestion_avoided?: number;
    food_backlog_avoided?: number;
    satisfaction_lift?: number;
  };
  causal_replay?: {
    actual?: Array<{ minute?: number; digest?: Record<string, unknown> }>;
    baseline?: Array<{ minute?: number; digest?: Record<string, unknown> }>;
    action_minute?: number;
  };
  agent_loop?: Array<{ stage?: string; label?: string; status?: string }>;
};

export const MAP_LAYERS: Array<{ id: MapLayer; label: string; detail: string }> = [
  { id: "overview", label: "All", detail: "Balanced live view" },
  { id: "attractions", label: "Attractions", detail: "Rides, shows, food, landmarks" },
  { id: "queues", label: "Queues", detail: "Spillback, wait, shade" },
  { id: "guests", label: "Guests", detail: "Segments, mood, destination" },
  { id: "support", label: "Support", detail: "Customer support agents and recommendation kiosks" },
  { id: "operations", label: "Ops", detail: "Service roads and facilities" },
  { id: "signals", label: "Signals", detail: "Live alerts and density" },
];

export const MAP_FOCUS_POINTS = [
  { label: "Whole park", x: 500, y: 325, zoom: 1 },
  { label: "Coaster", x: 735, y: 245, zoom: 1.85 },
  { label: "Food", x: 690, y: 488, zoom: 1.75 },
  { label: "Indoor", x: 300, y: 250, zoom: 1.7 },
  { label: "Entry", x: 235, y: 515, zoom: 1.65 },
];

export function viewBoxForFocus(focus: { x: number; y: number }, zoom: number) {
  const width = 1000 / zoom;
  const height = 650 / zoom;
  const x = Math.max(0, Math.min(1000 - width, focus.x - width / 2));
  const y = Math.max(0, Math.min(650 - height, focus.y - height / 2));
  return `${x} ${y} ${width} ${height}`;
}

export function landmarkTextAnchor(landmark: { x: number; y: number; w: number; h: number }) {
  return {
    x: landmark.x + Math.min(14, Math.max(8, landmark.w * 0.06)),
    y: landmark.y + Math.min(24, Math.max(16, landmark.h * 0.24)),
  };
}

function selectionTone(status?: string, pressure?: number): MapSelection["tone"] {
  const normalized = status?.toLowerCase() ?? "";
  if (normalized.includes("critical") || normalized.includes("down") || (pressure ?? 0) >= 85) return "risk";
  if (normalized.includes("watch") || normalized.includes("constrained") || (pressure ?? 0) >= 65) return "watch";
  return "ok";
}

function selectionStroke(tone: MapSelection["tone"]) {
  if (tone === "risk") return "#f97316";
  if (tone === "watch") return "#facc15";
  return "#22d3ee";
}

function clockPressureColor(value: number) {
  if (value >= 85) return "#dc2626";
  if (value >= 68) return "#d97706";
  return "#0891b2";
}

function clockWavePoint(wave: string) {
  if (wave === "lunch") return MAP_POINTS.foodCourtA;
  if (wave === "parade_release" || wave === "afternoon_parade") return MAP_POINTS.paradeRoute;
  if (wave === "show_release" || wave === "theater_matinee_release") return MAP_POINTS.theaterB;
  if (wave === "fireworks_preload" || wave === "fireworks_release") return MAP_POINTS.fireworksViewing;
  if (wave === "exit_wave" || wave === "park_close_exit") return MAP_POINTS.frontGate;
  if (wave === "ride_wave" || wave === "rope_drop") return MAP_POINTS.dragonCoaster;
  return MAP_POINTS.coveredPlaza;
}

function OperatingClockMapOverlay({
  clock,
  showLabels,
}: {
  clock: NonNullable<ParkState["operatingClock"]>;
  showLabels: boolean;
}) {
  const wavePoint = clockWavePoint(clock.phase.eventWave);
  const waveColor = clockPressureColor(clock.phase.demandPressurePct);
  const intentRoutes = [
    { id: "ride", label: "ride", value: clock.guestIntent.rideSeekingPct, to: MAP_POINTS.dragonCoaster, color: "#7c3aed" },
    { id: "food", label: "food", value: clock.guestIntent.foodSeekingPct, to: MAP_POINTS.foodCourtA, color: "#ea580c" },
    { id: "rest", label: "rest", value: clock.guestIntent.restSeekingPct, to: MAP_POINTS.indoorHub, color: "#0891b2" },
    { id: "exit", label: "exit", value: clock.guestIntent.exitSeekingPct, to: MAP_POINTS.frontGate, color: "#475569" },
  ].filter((route) => route.value >= 35);
  const pressureNodes = [
    { id: "staff", label: "Staff cycle", point: MAP_POINTS.staffBase, value: clock.staffLifecycle.breakPressurePct, color: "#f59e0b" },
    { id: "dispatch", label: "Dispatch friction", point: MAP_POINTS.dragonCoaster, value: clock.rideLifecycle.dispatchFrictionPct, color: "#dc2626" },
    { id: "food", label: "Prep pressure", point: MAP_POINTS.foodCourtA, value: clock.foodRetailLifecycle.prepPressurePct, color: "#ea580c" },
    { id: "event", label: "Event wave", point: MAP_POINTS.coveredPlaza, value: clock.eventSchedule.paradeRoutePressurePct, color: "#7c3aed" },
    { id: "care", label: "Care lag", point: MAP_POINTS.firstAid, value: clock.guestFeedbackLoop.careCaseAccumulationPct, color: "#0f766e" },
  ];

  return (
    <g>
      <circle cx={wavePoint.x} cy={wavePoint.y} r={52 + clock.phase.demandPressurePct * 0.45} fill={waveColor} opacity="0.11" />
      <circle className="park-node-pulse-svg" cx={wavePoint.x} cy={wavePoint.y} r={30} fill={waveColor} opacity="0.2" />
      <circle cx={wavePoint.x} cy={wavePoint.y} r={13} fill={waveColor} stroke="#fff7ed" strokeWidth="4" />

      {intentRoutes.map((route, index) => {
        const width = Math.max(4, Math.min(12, route.value / 8));
        const controlX = 500 + index * 28;
        const controlY = 370 - index * 20;
        return (
          <g key={route.id}>
            <path
              className="park-flow-line"
              d={`M${wavePoint.x} ${wavePoint.y} C${controlX} ${controlY} ${controlX + 40} ${controlY - 42} ${route.to.x} ${route.to.y}`}
              stroke={route.color}
              strokeLinecap="round"
              strokeWidth={width}
              fill="none"
              opacity="0.42"
            />
            {showLabels && (
              <g transform={`translate(${Math.min(880, Math.max(40, route.to.x + 18))} ${Math.max(42, route.to.y - 26)})`}>
                <rect width="72" height="28" rx="7" fill="#fff7ed" stroke={route.color} strokeWidth="2" opacity="0.94" />
                <text x="8" y="12" fill="#292524" fontSize="8.5" fontWeight="900">{route.label.toUpperCase()}</text>
                <text x="8" y="23" fill={route.color} fontSize="9" fontWeight="900">{pct(route.value)}</text>
              </g>
            )}
          </g>
        );
      })}

      {pressureNodes.map((node) => (
        <g key={node.id}>
          <circle cx={node.point.x} cy={node.point.y} r={18 + node.value * 0.28} fill={node.color} opacity={node.value >= 68 ? "0.18" : "0.1"} />
          <circle cx={node.point.x} cy={node.point.y} r="8" fill={node.color} stroke="#fff7ed" strokeWidth="3" />
          {showLabels && (
            <g transform={`translate(${Math.min(846, node.point.x + 20)} ${Math.max(34, node.point.y + 18)})`}>
              <rect width="128" height="34" rx="8" fill="#f8fafc" stroke={node.color} strokeWidth="2" opacity="0.94" />
              <text x="9" y="14" fill="#0f172a" fontSize="9" fontWeight="900">{node.label}</text>
              <text x="9" y="27" fill={node.color} fontSize="9" fontWeight="900">{pct(node.value)}</text>
            </g>
          )}
        </g>
      ))}

      {showLabels && (
        <g transform={`translate(${Math.max(20, Math.min(770, wavePoint.x - 90))} ${Math.max(56, wavePoint.y - 92)})`}>
          <rect width="204" height="54" rx="11" fill="#0f172a" stroke={waveColor} strokeWidth="3" opacity="0.92" />
          <text x="12" y="17" fill="#67e8f9" fontSize="9" fontWeight="900">OPERATING CLOCK</text>
          <text x="12" y="33" fill="#f8fafc" fontSize="11" fontWeight="900">{clock.phase.label.slice(0, 27)}</text>
          <text x="12" y="47" fill="#cbd5e1" fontSize="9" fontWeight="800">{clock.phase.eventWave.replaceAll("_", " ")} / next {clock.phase.nextPhaseInMinutes}m</text>
        </g>
      )}
    </g>
  );
}

function eventRoutePoints(eventId: string): MapPoint[] {
  if (eventId === "afternoon_parade") {
    return [MAP_POINTS.frontGate, MAP_POINTS.mainStreet, MAP_POINTS.paradeRoute, MAP_POINTS.coveredPlaza, MAP_POINTS.coasterPlaza];
  }
  if (eventId === "theater_matinee_release") {
    return [MAP_POINTS.theaterB, MAP_POINTS.indoorHub, MAP_POINTS.foodCourtA, MAP_POINTS.arcade];
  }
  if (eventId === "fireworks_preload") {
    return [MAP_POINTS.foodCourtA, MAP_POINTS.coveredPlaza, MAP_POINTS.fireworksViewing];
  }
  if (eventId === "fireworks_release" || eventId === "park_close_exit") {
    return [MAP_POINTS.fireworksViewing, MAP_POINTS.coveredPlaza, MAP_POINTS.mainStreet, MAP_POINTS.frontGate];
  }
  return [MAP_POINTS.coveredPlaza, MAP_POINTS.frontGate];
}

function eventTone(event: { kind?: string; trafficRiskPct?: number }) {
  if ((event.trafficRiskPct ?? 0) >= 86) return "#dc2626";
  if (event.kind === "fireworks" || event.kind === "fireworks_release") return "#7c3aed";
  if (event.kind === "parade") return "#f97316";
  return "#0891b2";
}

function ShowtimeMapOverlay({ clock }: { clock: NonNullable<ParkState["operatingClock"]> }) {
  const activeEvents = clock.eventSchedule.activeEvents ?? [];
  const nextEvent = clock.eventSchedule.nextEvent;
  const events = activeEvents.length ? activeEvents : nextEvent ? [nextEvent] : [];
  if (!events.length) return null;

  return (
    <g>
      {events.slice(0, 3).map((event, eventIndex) => {
        const tone = eventTone(event);
        const route = eventRoutePoints(event.id);
        const routePath = pointsToPath(route.map((point) => [point.x, point.y] as [number, number]));
        const anchor = route[Math.min(route.length - 1, Math.max(0, Math.floor(route.length / 2)))];
        const risk = event.trafficRiskPct ?? 0;
        return (
          <g key={event.id}>
            <path
              className="park-flow-line"
              d={routePath}
              stroke={tone}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={Math.max(9, Math.min(24, risk / 4))}
              strokeDasharray={event.solvedByPolicy ? "6 13" : "22 12"}
              fill="none"
              opacity={event.solvedByPolicy ? "0.34" : "0.46"}
            />
            {route.map((point, index) => (
              <circle key={`${event.id}-${point.label}-${index}`} cx={point.x} cy={point.y} r={9 + risk / 12} fill={tone} opacity={index === 0 ? "0.18" : "0.12"} />
            ))}
            <g transform={`translate(${Math.min(770, Math.max(36, anchor.x - 80 + eventIndex * 26))} ${Math.min(570, Math.max(50, anchor.y - 76 + eventIndex * 42))})`}>
              <rect width="214" height="66" rx="11" fill="#fff7ed" stroke={tone} strokeWidth="3" opacity="0.95" />
              <text x="11" y="17" fill={tone} fontSize="9" fontWeight="900">SCHEDULED CROWD WAVE</text>
              <text x="11" y="34" fill="#0f172a" fontSize="11" fontWeight="900">{event.name.slice(0, 28)}</text>
              <text x="11" y="49" fill="#334155" fontSize="9" fontWeight="900">{event.startTime} · {event.phase} · {pct(risk)}</text>
              <text x="11" y="61" fill={event.solvedByPolicy ? "#047857" : "#b45309"} fontSize="8.5" fontWeight="900">
                {event.solvedByPolicy ? "mitigation active" : "needs route split"}
              </text>
            </g>
          </g>
        );
      })}
    </g>
  );
}

function FastLaneFairnessMapOverlay({ clock }: { clock: NonNullable<ParkState["operatingClock"]> }) {
  const fairness = clock.accessFairness;
  if (!fairness) return null;
  const tone = fairness.publicComplaintRiskPct >= 76 ? "#dc2626" : fairness.publicComplaintRiskPct >= 55 ? "#d97706" : "#059669";
  const standbyWidth = Math.max(8, Math.min(20, fairness.standbyLaneSharePct / 4.8));
  const premiumWidth = Math.max(5, Math.min(14, fairness.premiumLaneSharePct / 4.6));

  return (
    <g>
      <path
        d={`M${MAP_POINTS.coasterPlaza.x - 54} ${MAP_POINTS.coasterPlaza.y + 62} C${MAP_POINTS.coasterPlaza.x - 16} ${MAP_POINTS.coasterPlaza.y + 20} ${MAP_POINTS.dragonCoaster.x - 28} ${MAP_POINTS.dragonCoaster.y + 34} ${MAP_POINTS.dragonCoaster.x + 10} ${MAP_POINTS.dragonCoaster.y + 8}`}
        stroke="#475569"
        strokeLinecap="round"
        strokeWidth={standbyWidth}
        fill="none"
        opacity="0.42"
      />
      <path
        className="park-flow-line"
        d={`M${MAP_POINTS.dragonCoaster.x + 92} ${MAP_POINTS.dragonCoaster.y - 44} C${MAP_POINTS.dragonCoaster.x + 64} ${MAP_POINTS.dragonCoaster.y - 10} ${MAP_POINTS.dragonCoaster.x + 42} ${MAP_POINTS.dragonCoaster.y + 10} ${MAP_POINTS.dragonCoaster.x + 10} ${MAP_POINTS.dragonCoaster.y + 8}`}
        stroke={tone}
        strokeLinecap="round"
        strokeWidth={premiumWidth}
        strokeDasharray={fairness.solvedByPolicy ? "6 10" : undefined}
        fill="none"
        opacity="0.62"
      />
      <circle cx={MAP_POINTS.dragonCoaster.x + 10} cy={MAP_POINTS.dragonCoaster.y + 8} r={26 + fairness.publicComplaintRiskPct * 0.22} fill={tone} opacity="0.13" />
      <circle cx={MAP_POINTS.dragonCoaster.x + 10} cy={MAP_POINTS.dragonCoaster.y + 8} r="12" fill={tone} stroke="#fff7ed" strokeWidth="4" />
      <g transform={`translate(${Math.max(40, MAP_POINTS.dragonCoaster.x - 122)} ${Math.max(40, MAP_POINTS.dragonCoaster.y - 104)})`}>
        <rect width="246" height="76" rx="11" fill="#fff7ed" stroke={tone} strokeWidth="3" opacity="0.96" />
        <text x="12" y="17" fill={tone} fontSize="9" fontWeight="900">FAST LANE FAIRNESS</text>
        <text x="12" y="34" fill="#0f172a" fontSize="10" fontWeight="900">VIP {pct(fairness.premiumLaneSharePct)} / standby +{fairness.standbyDelayDeltaMins}m</text>
        <text x="12" y="49" fill="#334155" fontSize="9" fontWeight="900">Complaint risk {pct(fairness.publicComplaintRiskPct)} · {fairness.status}</text>
        <text x="12" y="63" fill={fairness.solvedByPolicy ? "#047857" : "#b45309"} fontSize="8.5" fontWeight="900">
          {fairness.solvedByPolicy ? "merge cap active" : "needs merge cap + explanation"}
        </text>
      </g>
    </g>
  );
}

const IMPACT_REPLAY_PHASES = ["before", "baseline", "action", "after"] as const;
type ImpactReplayPhase = (typeof IMPACT_REPLAY_PHASES)[number];

function impactReplayPhaseMeta(phase: ImpactReplayPhase) {
  if (phase === "before") return { label: "Before", title: "Before pressure", color: "#f97316", detail: "Live pressure before the action" };
  if (phase === "baseline") return { label: "Baseline", title: "No-agent baseline", color: "#ef4444", detail: "Projected if the agent waits" };
  if (phase === "action") return { label: "Action", title: "Agent action", color: "#22d3ee", detail: "Receiver payloads and route changes" };
  return { label: "After", title: "After delta", color: "#22c55e", detail: "Actual state after the agent" };
}

function ReplayPhaseControls({
  phase,
  hasAfterState,
  className = "left-1/2 top-4 w-[min(35rem,calc(100%-1.5rem))] -translate-x-1/2",
  onPhaseChange,
}: {
  phase: ImpactReplayPhase;
  hasAfterState: boolean;
  className?: string;
  onPhaseChange: (phase: ImpactReplayPhase) => void;
}) {
  return (
    <div className={`pointer-events-auto absolute z-50 rounded-xl border border-white/35 bg-slate-950/90 p-2 text-slate-100 shadow-2xl backdrop-blur ${className}`}>
      <div className="mb-1 flex items-center justify-between gap-2 px-1">
        <div className="text-[9px] font-black uppercase tracking-widest text-cyan-300">Map replay timeline</div>
        <div className="text-[8px] font-black uppercase tracking-widest text-slate-500">{hasAfterState ? "after state available" : "overlay only"}</div>
      </div>
      <div className="grid grid-cols-4 gap-1">
        {IMPACT_REPLAY_PHASES.map((item) => {
          const meta = impactReplayPhaseMeta(item);
          const active = phase === item;
          return (
            <button
              key={item}
              type="button"
              onClick={() => onPhaseChange(item)}
              className={`rounded-lg px-2 py-2 text-left transition ${
                active ? "bg-cyan-300 text-slate-950" : "bg-white/10 text-slate-300 hover:bg-white/15 hover:text-white"
              }`}
            >
              <div className="text-[9px] font-black uppercase tracking-widest">{meta.label}</div>
              <div className="mt-0.5 line-clamp-1 text-[9px] font-bold opacity-75">{item === "baseline" ? "No agent" : meta.detail}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function AgentMapGroundingOverlay({
  grounding,
  impactReplay,
  replayPhase: controlledReplayPhase,
  physicalMap,
  flow,
}: {
  grounding?: AgentMapGrounding | null;
  impactReplay?: AgentImpactReplay | null;
  replayPhase?: ImpactReplayPhase;
  physicalMap: ParkPhysicalMap;
  flow: GuestFlow;
}) {
  const [replayPhase, setReplayPhase] = useState<ImpactReplayPhase>("before");
  useEffect(() => {
    if (controlledReplayPhase) {
      setReplayPhase(controlledReplayPhase);
      return;
    }
    if (!impactReplay) {
      setReplayPhase("before");
      return;
    }
    setReplayPhase("before");
    let index = 0;
    const interval = window.setInterval(() => {
      index = (index + 1) % IMPACT_REPLAY_PHASES.length;
      setReplayPhase(IMPACT_REPLAY_PHASES[index]);
    }, 1700);
    return () => window.clearInterval(interval);
  }, [controlledReplayPhase, impactReplay?.created_at, impactReplay?.action_plan?.id]);
  if (!grounding && !impactReplay) return null;
  const impact = impactReplay?.comparison?.impact;
  const delta = impactReplay?.map_delta;
  const phaseMeta = impactReplayPhaseMeta(replayPhase);
  const isBeforePhase = replayPhase === "before";
  const isBaselinePhase = replayPhase === "baseline";
  const isActionPhase = replayPhase === "action";
  const isAfterPhase = replayPhase === "after";
  const zoneIds = new Set(grounding?.highlight_zone_ids ?? []);
  const landmarkIds = new Set(grounding?.landmark_ids ?? []);
  const queueIds = new Set(grounding?.queue_ids ?? []);
  const pathIds = new Set(grounding?.path_ids ?? []);
  const zonePoints = flow.zones
    .filter((zone) => zoneIds.has(zone.id))
    .map((zone) => ({ id: `zone:${zone.id}`, label: zone.name, point: mapPointFor(zone.id), tone: zone.id === grounding?.primary_zone_id ? "#06b6d4" : "#f59e0b" }));
  const landmarkPoints = physicalMap.landmarks
    .filter((landmark) => landmarkIds.has(landmark.id))
    .map((landmark) => ({
      id: `landmark:${landmark.id}`,
      label: landmark.name,
      point: { x: landmark.x + landmark.w / 2, y: landmark.y + landmark.h / 2, label: landmark.name },
      tone: "#22d3ee",
    }));
  const queuePoints = physicalMap.queues
    .filter((queue) => queueIds.has(queue.id))
    .map((queue) => {
      const point = queue.points[Math.max(0, Math.floor(queue.points.length / 2) - 1)] ?? [500, 320];
      return { id: `queue:${queue.id}`, label: queue.name, point: { x: point[0], y: point[1], label: queue.name }, tone: "#f97316" };
    });
  const receiverPoints = (grounding?.receiver_targets ?? []).map((receiver, index) => ({
    id: `receiver:${receiver.channel ?? index}:${receiver.target ?? index}`,
    label: receiver.channel?.replaceAll("_", " ") ?? "receiver",
    point: mapPointFor(receiver.target, index === 0 ? MAP_POINTS.foodCourtA : index === 1 ? MAP_POINTS.staffBase : MAP_POINTS.coveredPlaza),
    tone: receiver.status === "sent" ? "#22c55e" : "#a78bfa",
  }));
  const points = [...zonePoints, ...landmarkPoints, ...queuePoints, ...receiverPoints].slice(0, 12);
  const routeSegments = Array.from(pathIds).map((id) => {
    const [from, to] = id.includes("->") ? id.split("->") : id.split(":");
    return { id, from: mapPointFor(from), to: mapPointFor(to) };
  }).filter((route) => route.from && route.to);

  return (
    <g>
      {routeSegments.map((route, index) => (
        <g key={`agent-route-${route.id}`}>
          <path
            className={isActionPhase || isAfterPhase ? "park-flow-line" : ""}
            d={`M${route.from.x} ${route.from.y} C${(route.from.x + route.to.x) / 2} ${Math.min(route.from.y, route.to.y) - 52 - index * 10} ${(route.from.x + route.to.x) / 2} ${Math.max(route.from.y, route.to.y) + 34} ${route.to.x} ${route.to.y}`}
            stroke={impactReplay ? phaseMeta.color : "#06b6d4"}
            strokeLinecap="round"
            strokeWidth={isBaselinePhase ? "16" : isAfterPhase ? "12" : "10"}
            strokeDasharray={isActionPhase || isAfterPhase ? "18 10" : "8 12"}
            fill="none"
            opacity={isBeforePhase ? "0.18" : isBaselinePhase ? "0.5" : "0.68"}
          />
          {isBaselinePhase && (
            <circle className="park-node-pulse-svg" cx={route.to.x} cy={route.to.y} r="54" fill="#ef4444" opacity="0.14" />
          )}
        </g>
      ))}
      {points.map((item, index) => {
        const labelX = Math.min(830, Math.max(30, item.point.x + 18));
        const labelY = Math.min(585, Math.max(38, item.point.y - 48 + (index % 3) * 18));
        const pointTone = impactReplay ? phaseMeta.color : item.tone;
        const pointRadius = isBaselinePhase ? 56 : isBeforePhase ? 46 : isAfterPhase ? 34 : 42;
        return (
          <g key={item.id}>
            <circle className="park-node-pulse-svg" cx={item.point.x} cy={item.point.y} r={pointRadius} fill={pointTone} opacity={isAfterPhase ? "0.14" : "0.22"} />
            <circle cx={item.point.x} cy={item.point.y} r={isAfterPhase ? "15" : "18"} fill={pointTone} stroke="#f8fafc" strokeWidth="5" />
            <circle cx={item.point.x} cy={item.point.y} r="7" fill="#0f172a" opacity="0.82" />
            {index < 6 && (
              <g transform={`translate(${labelX} ${labelY})`}>
                <rect width="154" height="42" rx="9" fill="#0f172a" stroke={pointTone} strokeWidth="2.5" opacity="0.94" />
                <text x="10" y="15" fill={pointTone} fontSize="8.5" fontWeight="900">{impactReplay ? phaseMeta.title.toUpperCase() : "AGENT GROUNDED"}</text>
                <text x="10" y="31" fill="#f8fafc" fontSize="10" fontWeight="900">{item.label.slice(0, 24)}</text>
              </g>
            )}
          </g>
        );
      })}
      {points.length > 0 && (
        <g transform="translate(34 38)">
          <rect width="260" height={impactReplay ? "78" : "56"} rx="12" fill="#0f172a" stroke={impactReplay ? phaseMeta.color : "#22d3ee"} strokeWidth="3" opacity="0.94" />
          <text x="12" y="18" fill={impactReplay ? phaseMeta.color : "#67e8f9"} fontSize="9" fontWeight="900">{impactReplay ? "MAP DELTA REPLAY" : "COPILOT MAP GROUNDING"}</text>
          <text x="12" y="35" fill="#f8fafc" fontSize="10" fontWeight="900">{impactReplay ? phaseMeta.title : grounding?.focus === "action_receipt" ? "Answer tied to dispatched receivers" : "Answer tied to live pressure"}</text>
          <text x="12" y="48" fill="#cbd5e1" fontSize="8.5" fontWeight="800">{impactReplay ? phaseMeta.detail : `${points.length} objects / ${routeSegments.length} route constraints`}</text>
          {impactReplay && (
            <g transform="translate(12 58)">
              {IMPACT_REPLAY_PHASES.map((phase, index) => {
                const meta = impactReplayPhaseMeta(phase);
                const active = replayPhase === phase;
                return (
                  <g key={phase} transform={`translate(${index * 60} 0)`}>
                    <rect width="52" height="12" rx="4" fill={active ? meta.color : "#1e293b"} opacity={active ? "0.95" : "0.8"} />
                    <text x="26" y="9" textAnchor="middle" fill={active ? "#020617" : "#94a3b8"} fontSize="6.8" fontWeight="900">{meta.label.toUpperCase()}</text>
                  </g>
                );
              })}
            </g>
          )}
        </g>
      )}
      {impactReplay && (
        <g transform="translate(704 38)">
          <rect width="258" height="118" rx="13" fill="#0f172a" stroke={phaseMeta.color} strokeWidth="3" opacity="0.95" />
          <text x="12" y="18" fill={phaseMeta.color} fontSize="9" fontWeight="900">ACTION IMPACT REPLAY</text>
          <text x="12" y="35" fill="#f8fafc" fontSize="10" fontWeight="900">{phaseMeta.title}: {(impactReplay.action_plan?.label ?? "Copilot action measured").slice(0, 25)}</text>
          <text x="12" y="51" fill="#cbd5e1" fontSize="8.5" fontWeight="800">{impact?.headline?.slice(0, 44) ?? delta?.primary_metric?.slice(0, 44) ?? "Actual compared with no-agent baseline"}</text>
          {[
            ["Score", impactReplay.comparison?.score_lift],
            ["Wait", delta?.wait_minutes_avoided],
            ["Queue", delta?.queue_guests_avoided],
            ["Density", delta?.density_points_reduced],
          ].map(([label, value], index) => (
            <g key={String(label)} transform={`translate(${12 + (index % 2) * 118} ${64 + Math.floor(index / 2) * 24})`}>
              <rect width="108" height="19" rx="5" fill="#020617" stroke="#14532d" strokeWidth="1" opacity="0.88" />
              <text x="7" y="13" fill="#94a3b8" fontSize="7.5" fontWeight="900">{String(label).toUpperCase()}</text>
              <text x="76" y="13" fill={Number(value ?? 0) > 0 ? "#86efac" : "#cbd5e1"} fontSize="8.5" fontWeight="900" textAnchor="end">
                {typeof value === "number" ? (value > 0 ? `+${value}` : String(value)) : "--"}
              </text>
            </g>
          ))}
        </g>
      )}
    </g>
  );
}

export type MapTimeLens = "past" | "now" | "future";

function timeLensTitle(lens: MapTimeLens) {
  if (lens === "past") return "PAST GHOST";
  if (lens === "future") return "+15M PROJECTED";
  return "NOW LIVE";
}

function timeLensTone(lens: MapTimeLens) {
  if (lens === "past") return "#64748b";
  if (lens === "future") return "#8b5cf6";
  return "#06b6d4";
}

function timeLensQueueDelta(lens: MapTimeLens, clock?: ParkState["operatingClock"]) {
  const pressure = clock?.phase.demandPressurePct ?? 74;
  const dispatch = clock?.rideLifecycle.dispatchFrictionPct ?? 38;
  if (lens === "past") return -Math.max(35, Math.round((pressure + dispatch) * 1.4));
  if (lens === "future") return Math.max(45, Math.round((pressure + dispatch) * 1.9));
  return 0;
}

function TimeLapseMapOverlay({
  lens,
  physicalMap,
  flow,
  clock,
}: {
  lens: MapTimeLens;
  physicalMap: ParkPhysicalMap;
  flow: GuestFlow;
  clock?: ParkState["operatingClock"];
}) {
  const tone = timeLensTone(lens);
  const queueDelta = timeLensQueueDelta(lens, clock);
  const topQueues = [...physicalMap.queues]
    .sort((left, right) => right.waitMins + right.guests / 25 - (left.waitMins + left.guests / 25))
    .slice(0, 3);
  const topGroups = [...physicalMap.guestGroups]
    .sort((left, right) => right.count - left.count)
    .slice(0, 4);
  const topZones = [...flow.zones]
    .sort((left, right) => right.density + right.waitMins - (left.density + left.waitMins))
    .slice(0, 3);
  const label = timeLensTitle(lens);
  const opacity = lens === "now" ? 0.52 : 0.34;

  return (
    <g>
      <g transform="translate(38 112)">
        <rect width="194" height="58" rx="11" fill="#0f172a" stroke={tone} strokeWidth="3" opacity="0.92" />
        <text x="12" y="18" fill={tone} fontSize="10" fontWeight="900">{label}</text>
        <text x="12" y="35" fill="#f8fafc" fontSize="10" fontWeight="900">
          {lens === "past" ? "previous pressure ghost" : lens === "future" ? "near-future pressure" : "current operating frame"}
        </text>
        <text x="12" y="49" fill="#cbd5e1" fontSize="9" fontWeight="800">
          Queue {queueDelta > 0 ? "+" : ""}{queueDelta} guests / {clock?.phase.eventWave.replaceAll("_", " ") ?? "live wave"}
        </text>
      </g>

      {topQueues.map((queue, index) => {
        const path = pointsToPath(queue.points);
        const labelPoint = queue.points[Math.max(0, Math.floor(queue.points.length / 2) - 1)] ?? [500, 320];
        const projectedGuests = Math.max(0, queue.guests + queueDelta + index * 24);
        const projectedWait = Math.max(0, queue.waitMins + Math.round(queueDelta / 35) + index * 2);
        return (
          <g key={`${lens}-${queue.id}`}>
            <path
              d={path}
              stroke={tone}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={lens === "future" ? 24 : lens === "past" ? 18 : 14}
              strokeDasharray={lens === "now" ? undefined : "16 12"}
              fill="none"
              opacity={opacity}
            />
            <g transform={`translate(${labelPoint[0] - 8} ${labelPoint[1] + 18 + index * 8})`}>
              <rect width="116" height="32" rx="8" fill="#f8fafc" stroke={tone} strokeWidth="2" opacity="0.94" />
              <text x="8" y="13" fill="#0f172a" fontSize="9" fontWeight="900">{lens === "future" ? "+15m" : lens === "past" ? "-10m" : "now"} queue</text>
              <text x="8" y="26" fill={tone} fontSize="9" fontWeight="900">{projectedWait}m / {projectedGuests}</text>
            </g>
          </g>
        );
      })}

      {topGroups.map((group, index) => {
        const destination = mapPointFor(group.destination, MAP_POINTS.coveredPlaza);
        const progress = lens === "past" ? -0.18 : lens === "future" ? 0.34 : 0;
        const x = group.x + (destination.x - group.x) * progress;
        const y = group.y + (destination.y - group.y) * progress;
        const radius = Math.max(10, Math.min(30, Math.sqrt(group.count) * 1.25));
        return (
          <g key={`${lens}-${group.id}`}>
            {lens !== "past" && (
              <path
                className={lens === "future" ? "park-flow-line" : undefined}
                d={`M${group.x} ${group.y} C${(group.x + destination.x) / 2} ${group.y - 42 - index * 8} ${(group.x + destination.x) / 2} ${destination.y + 32} ${destination.x} ${destination.y}`}
                stroke={tone}
                strokeLinecap="round"
                strokeWidth={lens === "future" ? 7 : 4}
                strokeDasharray={lens === "now" ? "10 9" : undefined}
                fill="none"
                opacity={lens === "future" ? 0.46 : 0.24}
              />
            )}
            <circle cx={x} cy={y} r={radius + 8} fill={tone} opacity={lens === "future" ? "0.18" : "0.1"} />
            <circle cx={x} cy={y} r={radius} fill={tone} opacity={lens === "past" ? "0.28" : "0.52"} stroke="#fff7ed" strokeWidth="3" />
            {index < 2 && (
              <text x={x + radius + 8} y={y + 4} fill="#0f172a" fontSize="10" fontWeight="900">
                {lens === "future" ? "projected move" : lens === "past" ? "prior group" : "moving now"}
              </text>
            )}
          </g>
        );
      })}

      {topZones.map((zone) => {
        const layout = ZONE_LAYOUT[zone.id];
        if (!layout) return null;
        const cx = (layout.x + layout.w / 2) * 10;
        const cy = (layout.y + layout.h / 2) * 6.5;
        const projectedDensity = Math.max(0, Math.min(118, zone.density + (lens === "future" ? Math.round((clock?.phase.demandPressurePct ?? 70) / 12) : lens === "past" ? -8 : 0)));
        return (
          <g key={`${lens}-${zone.id}`}>
            <circle cx={cx} cy={cy} r={24 + projectedDensity * 0.24} fill={tone} opacity="0.1" />
            <text x={cx + 16} y={cy + 36} fill={tone} fontSize="9" fontWeight="900">
              {pct(projectedDensity)} {lens}
            </text>
          </g>
        );
      })}
    </g>
  );
}

export type AiParkPhase = "idle" | "running" | "complete";
export type AiStepStatus = "pending" | "active" | "done";
export type AiDemoStep = {
  id: "predict" | "decide" | "govern" | "emit" | "observe" | "learn";
  label: string;
  detail: string;
  metric: string;
  status: AiStepStatus;
};

export function aiPhaseForMap(isRunning: boolean, isRunningProactive?: boolean, hasResponse?: boolean): AiParkPhase {
  if (isRunning || isRunningProactive) return "running";
  return hasResponse ? "complete" : "idle";
}

export function aiPhaseLabel(phase: AiParkPhase) {
  if (phase === "running") return "AI acting now";
  if (phase === "complete") return "AI response visible";
  return "Awaiting AI run";
}

export function statusForStep(index: number, activeStep: number, phase: AiParkPhase): AiStepStatus {
  if (phase === "complete") return "done";
  if (phase === "idle") return index === 0 ? "active" : "pending";
  if (index < activeStep) return "done";
  if (index === activeStep) return "active";
  return "pending";
}

export function scenarioMapFocus(key: ScenarioKey) {
  if (key === "food_spike") {
    return {
      detect: { x: 690, y: 488, title: "Food demand", detail: "mobile backlog" },
      guest: { x: 584, y: 432, title: "Pickup reroute" },
      worker: { x: 674, y: 520, title: "Kitchen task" },
      ops: { x: 558, y: 518, title: "Stock move" },
      relief: "React: food queue splitting",
    };
  }
  if (key === "staff_shortage") {
    return {
      detect: { x: 558, y: 518, title: "Staff gap", detail: "coverage risk" },
      guest: { x: 260, y: 460, title: "Line support" },
      worker: { x: 510, y: 500, title: "Redeploy staff" },
      ops: { x: 690, y: 490, title: "Service lane" },
      relief: "React: staffed lanes opening",
    };
  }
  if (key === "storm_response") {
    return {
      detect: { x: 502, y: 344, title: "Storm shelter", detail: "HVAC pressure" },
      guest: { x: 350, y: 300, title: "Indoor route" },
      worker: { x: 510, y: 500, title: "Shelter staff" },
      ops: { x: 502, y: 344, title: "HVAC hold" },
      relief: "React: shelter load balanced",
    };
  }
  return {
    detect: { x: 735, y: 245, title: "Coaster pressure", detail: "queue + downtime" },
    guest: { x: 214, y: 228, title: "Guest reroute" },
    worker: { x: 676, y: 468, title: "Worker task" },
    ops: { x: 716, y: 278, title: "Ops hold" },
    relief: "React: queue pressure easing",
  };
}

function domainMapFocus(domain: unknown, fallback: ReturnType<typeof scenarioMapFocus>) {
  const key = String(domain ?? "").toLowerCase();
  if (key === "medical") {
    return {
      detect: { x: 516, y: 520, title: "Medical signal", detail: "care + access" },
      guest: { x: 438, y: 486, title: "Calm route" },
      worker: { x: 510, y: 500, title: "First aid team" },
      ops: { x: 510, y: 500, title: "Access clear" },
      relief: "React: care route protected",
    };
  }
  if (key === "crowd") {
    return {
      detect: { x: 570, y: 290, title: "Crowd pressure", detail: "path risk" },
      guest: { x: 280, y: 350, title: "Calm reroute" },
      worker: { x: 180, y: 540, title: "Crowd staff" },
      ops: { x: 510, y: 500, title: "Lane clear" },
      relief: "React: crowd dispersing",
    };
  }
  if (key === "energy") {
    return {
      detect: { x: 270, y: 190, title: "Comfort load", detail: "HVAC pressure" },
      guest: { x: 530, y: 345, title: "Comfort zone" },
      worker: { x: 510, y: 500, title: "Facilities" },
      ops: { x: 502, y: 344, title: "HVAC set" },
      relief: "React: comfort controls applied",
    };
  }
  return fallback;
}

export function scenarioProof(scenario: DemoScenario, telemetry?: ProactiveRunTelemetry | null, runTelemetry?: RunTelemetry | null) {
  const impact = telemetry?.lifecycle?.state_impact ?? telemetry?.outcome?.state_impact ?? runTelemetry?.outcome?.state_impact;
  const followThrough = telemetry?.delivery?.response?.reactiveFollowThroughRate ?? runTelemetry?.delivery?.response?.reactiveFollowThroughRate;
  const takeRate = telemetry?.delivery?.response?.takeRate ?? runTelemetry?.delivery?.response?.takeRate;
  const operatorConstraints = runTelemetry?.operator_constraints ?? runTelemetry?.optimization?.operator_constraints;
  const traceSummary = telemetry?.trace_contract?.ui_summary ?? runTelemetry?.trace_contract?.ui_summary;
  const selectedAction = runTelemetry?.planner?.selected_action?.label ?? traceSummary?.selected ?? telemetry?.lifecycle?.action_effects?.[0]?.label;
  const policyFinding = runTelemetry?.governance?.findings?.[0] ?? runTelemetry?.eval?.scorecard?.policy_gate_status ?? telemetry?.eval?.scorecard?.policy_gate_status;
  const dispatchCount = telemetry?.delivery?.summary?.total ?? runTelemetry?.delivery?.summary?.total;
  const learnedRows = telemetry?.analytics?.row_counts?.outcome_events ?? telemetry?.analytics?.inserted?.outcome_events;

  if (telemetry || runTelemetry) {
    return {
      before: operatorConstraints?.intent_summary ?? traceSummary?.input ?? runTelemetry?.request?.operator_command ?? "Live park state and operator request parsed.",
      after: impact?.headline ?? (typeof dispatchCount === "number" ? `${dispatchCount} receiver payloads emitted` : "Runtime action prepared for receivers."),
      signal: operatorConstraints?.intent_summary ?? traceSummary?.input ?? "Gemini used live state, operator text, memory, and policy context.",
      policy: policyFinding ? `Safety check: ${policyFinding}` : "Safety check completed before receiver dispatch.",
      action: selectedAction ?? "Custom action selected from this request.",
      result: takeRate ? `${ratePct(takeRate)} take / ${ratePct(followThrough)} follow` : learnedRows ? `${learnedRows} outcome rows ready for learning` : "Receiver response pending.",
    };
  }

  return {
    before: "Waiting for a live operator request.",
    after: "No custom action has been executed yet.",
    signal: "Type a park issue or trigger a live feed; the proof will be generated from the returned telemetry.",
    policy: "Safety check is ready for the next custom plan.",
    action: "No action selected.",
    result: "Receiver response pending.",
  };
}

type MapPoint = { x: number; y: number; label: string };
type RouteCue = { id: string; destination: string; zoneId: string; point: MapPoint; share?: number; rationale?: string };
type CustomActionOverlay = {
  source: MapPoint;
  routes: RouteCue[];
  avoidZones: Array<{ id: string; label: string; point: MapPoint; reason: string }>;
  staffMoves: Array<{ id: string; role: string; count?: number; from: MapPoint; to: MapPoint }>;
  hvacZones: Array<{ id: string; label: string; point: MapPoint; setpoint?: number }>;
  receiverActions: Array<{ id: string; channel: string; label: string; point: MapPoint; status?: string }>;
  headline: string;
  intentSummary?: string;
  incidentType?: string;
  rejectedOption?: string;
  primaryAction?: string;
  holdShare?: number;
  offerStrength?: string;
};

const MAP_POINTS: Record<string, MapPoint> = {
  frontGate: { x: 200, y: 545, label: "Front Gate" },
  dragonCoaster: { x: 735, y: 230, label: "Dragon Coaster" },
  coasterPlaza: { x: 735, y: 245, label: "Coaster Plaza" },
  arcade: { x: 530, y: 345, label: "Arcade" },
  arcadeZone: { x: 310, y: 312, label: "Arcade Zone" },
  theaterB: { x: 280, y: 350, label: "Theater B" },
  paradeRoute: { x: 455, y: 414, label: "Parade Route" },
  indoorHub: { x: 270, y: 190, label: "Indoor Hub" },
  indoorLaunch: { x: 260, y: 180, label: "Indoor Launch" },
  foodCourtA: { x: 690, y: 505, label: "Food Court A" },
  foodCourt1: { x: 715, y: 438, label: "Food Court A" },
  foodCourtB: { x: 330, y: 478, label: "Main Street Snacks" },
  snackStandC: { x: 526, y: 152, label: "Shade Garden Snacks" },
  coveredPlaza: { x: 570, y: 290, label: "Covered Plaza" },
  fireworksViewing: { x: 748, y: 402, label: "Fireworks Viewing" },
  lake: { x: 748, y: 438, label: "Central Lake" },
  firstAid: { x: 516, y: 520, label: "First Aid" },
  familyGarden: { x: 438, y: 486, label: "Family Garden" },
  familyZone: { x: 438, y: 486, label: "Family Garden" },
  shadeGarden: { x: 526, y: 152, label: "Shade garden" },
  mainStreet: { x: 330, y: 478, label: "Main Street Shops" },
  medicalAccess: { x: 510, y: 500, label: "Medical access" },
  securityBase: { x: 146, y: 520, label: "Security Base" },
  staffBase: { x: 180, y: 540, label: "Staff base" },
};

function normalizeId(value?: unknown) {
  return String(value ?? "").trim();
}

function mapPointFor(value?: unknown, fallback?: MapPoint): MapPoint {
  const key = normalizeId(value);
  const compact = key.toLowerCase().replaceAll("_", "").replaceAll(" ", "");
  const byLabel = Object.entries(MAP_POINTS).find(([id, point]) => id.toLowerCase() === compact || point.label.toLowerCase().replaceAll(" ", "") === compact)?.[1];
  return MAP_POINTS[key] ?? MAP_POINTS[key.replaceAll("_", "")] ?? byLabel ?? fallback ?? MAP_POINTS.coveredPlaza;
}

function commandMentions(command: string | undefined, terms: string[]) {
  const text = (command ?? "").toLowerCase();
  return terms.some((term) => text.includes(term));
}

function payloadRecord(dispatch?: DeliveryDispatch) {
  return (dispatch?.payload ?? {}) as Record<string, unknown>;
}

function routeCuesFromDispatch(guestDispatch: DeliveryDispatch | undefined, scenario: DemoScenario, operatorCommand?: string): RouteCue[] {
  const payload = payloadRecord(guestDispatch);
  const targetMix = Array.isArray(payload.targetMix) ? payload.targetMix as Array<Record<string, unknown>> : [];
  const routingTargets = Array.isArray(payload.routingTargets) ? payload.routingTargets as unknown[] : [];
  const targetRecords: Array<Record<string, unknown>> = targetMix.length
    ? targetMix
    : routingTargets.map((target, index) => ({
        destination: target,
        destinationId: target,
        share: index === 0 ? 0.46 : index === 1 ? 0.28 : 0.18,
      }));
  const routes = targetRecords
    .map((target, index) => {
      const zoneId = normalizeId(target.zoneId ?? target.destinationId ?? target.destination);
      const destination = normalizeId(target.destination) || mapPointFor(zoneId).label;
      const share = typeof target.share === "number" ? target.share : undefined;
      return {
        id: `${zoneId || destination}-${index}`,
        destination,
        zoneId,
        point: mapPointFor(zoneId || destination),
        share,
        rationale: normalizeId(target.rationale),
      };
    })
    .filter((route) => route.destination);

  if (routes.length) return routes.slice(0, 3);
  if (guestDispatch) return [];
  if (operatorCommand?.trim()) return [];

  const defaults: RouteCue[] =
    scenario.key === "food_spike"
      ? [
          { id: "food-alt", destination: "Main Street Shops", zoneId: "mainStreet", point: { x: 330, y: 478, label: "Main Street Shops" }, share: 0.42 },
          { id: "shade", destination: "Shade garden", zoneId: "shadeGarden", point: { x: 526, y: 152, label: "Shade garden" }, share: 0.22 },
        ]
      : scenario.key === "storm_response"
        ? [
            { id: "indoor", destination: "Indoor Hub", zoneId: "indoorHub", point: MAP_POINTS.indoorHub, share: 0.46 },
            { id: "theater", destination: "Theater B", zoneId: "theaterB", point: MAP_POINTS.theaterB, share: 0.24 },
          ]
        : [
            { id: "arcade", destination: "Arcade Zone", zoneId: "arcadeZone", point: MAP_POINTS.arcade, share: commandMentions(operatorCommand, ["arcade"]) ? 0.48 : 0.4 },
            { id: "theater", destination: "Theater B", zoneId: "theaterB", point: MAP_POINTS.theaterB, share: 0.24 },
          ];

  return defaults;
}

function buildCustomActionOverlay({
  scenario,
  dispatches,
  operatorCommand,
  runTelemetry,
  proactiveRunTelemetry,
  operatorCommandResult,
}: {
  scenario: DemoScenario;
  dispatches: DeliveryDispatch[];
  operatorCommand?: string;
  runTelemetry?: RunTelemetry | null;
  proactiveRunTelemetry?: ProactiveRunTelemetry | null;
  operatorCommandResult?: OperatorCommandResponse | null;
}): CustomActionOverlay {
  const guestDispatch = dispatchForChannel(dispatches, "guest_app");
  const workerDispatch = dispatchForChannel(dispatches, "worker_device");
  const equipmentDispatch = dispatchForChannel(dispatches, "equipment_controller");
  const guestPayload = payloadRecord(guestDispatch);
  const workerPayload = payloadRecord(workerDispatch);
  const equipmentPayload = payloadRecord(equipmentDispatch);
  const operatorConstraints = runTelemetry?.operator_constraints ?? runTelemetry?.optimization?.operator_constraints;
  const operatorFrame = runTelemetry?.optimization?.operator_candidate_frame;
  const selectedAction = runTelemetry?.planner?.selected_action?.label;
  const proactiveAction = proactiveRunTelemetry?.lifecycle?.action_effects?.[0]?.label;
  const headline =
    operatorCommandResult?.gemini_refinement?.headline ??
    operatorCommandResult?.operator_response?.headline ??
    operatorConstraints?.intent_summary ??
    selectedAction ??
    proactiveAction ??
    "Waiting for custom agent action";
  const primaryTarget = runTelemetry?.planner?.selected_action?.target ?? operatorFrame?.primary_action?.target;
  const incidentTarget = operatorConstraints?.safety_escalations?.[0]?.target;
  const firstStaffMove = operatorConstraints?.required_staff_moves?.[0];
  const workerTarget = normalizeId(workerPayload.targetZone);
  const commandSource =
    commandMentions(operatorCommand, ["food", "kitchen", "restaurant", "mobile order"])
      ? MAP_POINTS.foodCourtA
      : commandMentions(operatorCommand, ["medical", "faint", "injury", "wheelchair", "accessibility", "handicapped"])
        ? MAP_POINTS.firstAid
        : commandMentions(operatorCommand, ["security", "fight", "panic", "evac"])
          ? MAP_POINTS.securityBase
          : MAP_POINTS.coveredPlaza;
  const source =
    incidentTarget
      ? mapPointFor(incidentTarget, MAP_POINTS.coveredPlaza)
      : workerTarget
        ? mapPointFor(workerTarget, MAP_POINTS.coveredPlaza)
        : primaryTarget === "medical"
          ? MAP_POINTS.firstAid
          : primaryTarget === "accessibility"
            ? MAP_POINTS.familyGarden
            : primaryTarget === "security"
              ? MAP_POINTS.coveredPlaza
              : scenario.key === "food_spike"
      ? MAP_POINTS.foodCourtA
      : scenario.key === "storm_response"
        ? MAP_POINTS.coveredPlaza
        : commandSource;

  const avoidZones: CustomActionOverlay["avoidZones"] = [];
  const avoidValues = [
    ...(operatorConstraints?.avoid_zones ?? []),
    ...(Array.isArray(guestPayload.avoidExtraDemandAt) ? guestPayload.avoidExtraDemandAt : []),
    ...(commandMentions(operatorCommand, ["food court a", "food court 1", "avoid food", "stop sending guests there", "stop sending guests to food"]) ? ["foodCourtA"] : []),
    ...(commandMentions(operatorCommand, ["not indoor launch", "avoid indoor launch"]) ? ["indoorHub"] : []),
  ];
  avoidValues.forEach((value) => {
    const valueRecord = typeof value === "object" && value !== null ? value as Record<string, unknown> : undefined;
    const id = normalizeId(valueRecord?.id ?? valueRecord?.name ?? value);
    const point = mapPointFor(id, MAP_POINTS.foodCourtA);
    const label = normalizeId(valueRecord?.name) || point.label;
    if (!avoidZones.some((zone) => zone.id === id || zone.label === point.label)) {
      avoidZones.push({ id: id || label, label, point, reason: normalizeId(valueRecord?.reason) || "Avoid per command or capacity gate" });
    }
  });

  const constraintStaffMoves = operatorConstraints?.required_staff_moves ?? [];
  const staffMovesRaw = constraintStaffMoves.length
    ? constraintStaffMoves
    : Array.isArray(guestPayload.staffMoves)
      ? guestPayload.staffMoves
      : Array.isArray(workerPayload.staffMoves)
        ? workerPayload.staffMoves
        : [];
  const staffMoves = (staffMovesRaw as Array<Record<string, unknown>>).map((move, index) => ({
    id: `staff-${index}`,
    role: normalizeId(move.role) || normalizeId(workerPayload.role) || "crowd control",
    count: typeof move.count === "number" ? move.count : typeof workerPayload.count === "number" ? workerPayload.count : undefined,
    from: mapPointFor(move.from_location ?? move.fromLocation ?? move.from ?? "staffBase", MAP_POINTS.staffBase),
    to: mapPointFor(move.to_location ?? move.toLocation ?? move.to ?? workerPayload.targetZone ?? incidentTarget ?? "arcadeZone", MAP_POINTS.arcade),
  }));
  if (!staffMoves.length && (workerDispatch || commandMentions(operatorCommand, ["staff", "worker", "move"]))) {
    staffMoves.push({
      id: "staff-default",
      role: normalizeId(workerPayload.role) || "crowd control",
      count: typeof workerPayload.count === "number" ? workerPayload.count : 2,
      from: MAP_POINTS.staffBase,
      to: mapPointFor(workerPayload.targetZone ?? incidentTarget ?? source.label, source),
    });
  }

  const constraintEquipment = operatorConstraints?.equipment_controls?.[0];
  const hvacZonesRaw = Array.isArray(equipmentPayload.zones)
    ? equipmentPayload.zones
    : Array.isArray(constraintEquipment?.zones)
      ? constraintEquipment.zones
    : commandMentions(operatorCommand, ["hvac", "temperature", "comfort"])
      ? ["indoorHub", "arcadeZone"]
      : [];
  const hvacZones = (hvacZonesRaw as unknown[]).slice(0, 4).map((zone) => {
    const id = normalizeId(zone);
    const point = mapPointFor(id, MAP_POINTS.indoorHub);
    const settings = (equipmentPayload.settings ?? constraintEquipment?.settings ?? {}) as Record<string, unknown>;
    const setpoint =
      typeof settings[`${id}SetpointF`] === "number"
        ? settings[`${id}SetpointF`] as number
        : typeof settings.indoorHubSetpointF === "number"
          ? settings.indoorHubSetpointF as number
          : typeof settings.arcadeZoneSetpointF === "number"
            ? settings.arcadeZoneSetpointF as number
            : undefined;
    return { id: id || point.label, label: point.label, point, setpoint };
  });
  const receiverActions = dispatches.slice(0, 5).map((dispatch, index) => {
    const payload = payloadRecord(dispatch);
    const channel = normalizeId(dispatch.channel) || "receiver";
    const label =
      channel === "guest_app"
        ? "Guest app message"
        : channel === "worker_device"
          ? normalizeId(payload.role) || "Worker task"
          : normalizeId(payload.equipmentType) || normalizeId(payload.command) || "Equipment control";
    const target =
      payload.targetZone ??
      (Array.isArray(payload.zones) ? payload.zones[0] : undefined) ??
      incidentTarget ??
      firstStaffMove?.to ??
      source.label;
    return {
      id: dispatch.id ?? `receiver-${index}`,
      channel,
      label,
      point: mapPointFor(target, source),
      status: normalizeId(dispatch.status ?? dispatch.response?.state),
    };
  });

  return {
    source,
    routes: routeCuesFromDispatch(guestDispatch, scenario, operatorCommand),
    avoidZones,
    staffMoves,
    hvacZones,
    receiverActions,
    headline,
    intentSummary: operatorConstraints?.intent_summary,
    incidentType: operatorConstraints?.inferred_incident_type,
    rejectedOption: operatorConstraints?.rejected_option ?? operatorFrame?.rejected_options?.[0]?.reason,
    primaryAction: operatorFrame?.primary_action?.label,
    holdShare: typeof guestPayload.holdShare === "number" ? guestPayload.holdShare : undefined,
    offerStrength: normalizeId((guestPayload.promotion as Record<string, unknown> | undefined)?.strength ?? guestPayload.promotionStrength),
  };
}

export function buildAiDemoSteps({
  scenario,
  phase,
  activeStep,
  telemetry,
  runTelemetry,
}: {
  scenario: DemoScenario;
  phase: AiParkPhase;
  activeStep: number;
  telemetry?: ProactiveRunTelemetry | null;
  runTelemetry?: RunTelemetry | null;
}): AiDemoStep[] {
  const proof = scenarioProof(scenario, telemetry, runTelemetry);
  const dispatchCount = telemetry?.lifecycle?.metrics?.dispatch_total ?? telemetry?.delivery?.summary?.total ?? runTelemetry?.delivery?.summary?.total ?? 0;
  const learnCount = telemetry?.analytics?.row_counts?.outcome_events ?? telemetry?.analytics?.inserted?.outcome_events ?? 0;
  const responseScore = telemetry?.delivery?.response?.score ?? telemetry?.lifecycle?.metrics?.response_score ?? telemetry?.eval?.overall;

  const details = [
    ["predict", "Predict", proof.signal, telemetry || runTelemetry ? "live" : "ready"],
    ["decide", "Decide", proof.policy, runTelemetry?.governance?.gate_status ?? (telemetry || runTelemetry ? "gate" : "waiting")],
    ["govern", "Govern", proof.policy, runTelemetry?.governance?.allowed === false ? "review" : telemetry || runTelemetry ? "checked" : "waiting"],
    ["emit", "Emit", proof.action, `${dispatchCount} emits`],
    ["observe", "Observe", proof.after, responseScore ? `${responseScore}` : "observed"],
    ["learn", "Learn", "Outcome stored for the next model decision.", `${learnCount} row`],
  ] as const;

  return details.map(([id, label, detail, metric], index) => ({
    id,
    label,
    detail,
    metric,
    status: statusForStep(index, activeStep, phase),
  }));
}

function liveRuntimeLabel(telemetry?: ProactiveRunTelemetry | null, runTelemetry?: RunTelemetry | null) {
  const proof = telemetry?.runtime_proof;
  if (proof?.mode === "full_runtime") return proof.provider ?? proof.platform ?? proof.runtime ?? "Gemini live";
  if (proof?.mode === "bounded_fallback") return "Fast policy";
  if (runTelemetry?.planner?.runtime) return cleanRuntimeLabel(runTelemetry.planner.runtime);
  return telemetry || runTelemetry ? "Runtime returned" : "Gemini pending";
}

function liveModelLabel(telemetry?: ProactiveRunTelemetry | null, runTelemetry?: RunTelemetry | null) {
  return cleanRuntimeLabel(telemetry?.runtime_proof?.model ?? runTelemetry?.planner?.model ?? telemetry?.brief?.runtime ?? "model pending");
}

function cleanRuntimeLabel(value?: string | null) {
  const text = String(value ?? "");
  const lower = text.toLowerCase();
  if (lower.includes("bounded_action") || lower.includes("fast_operating")) return "Fast policy";
  if (lower.includes("fallback")) return "Preview";
  return text.replaceAll("_", " ");
}

function liveGateLabel(telemetry?: ProactiveRunTelemetry | null, runTelemetry?: RunTelemetry | null) {
  return runTelemetry?.governance?.gate_status ?? runTelemetry?.eval?.scorecard?.policy_gate_status ?? telemetry?.eval?.status ?? "policy checked";
}

function liveMemoryLabel(telemetry?: ProactiveRunTelemetry | null, runTelemetry?: RunTelemetry | null) {
  const memoryId =
    telemetry?.learning_proof?.memory_write?.outcome_id ??
    telemetry?.trace_contract?.memory_write?.outcome_id ??
    telemetry?.outcome_id ??
    runTelemetry?.trace_contract?.memory_write?.outcome_id ??
    runTelemetry?.outcome_id;
  if (memoryId) return memoryId;
  const rowCount = telemetry?.analytics?.inserted?.outcome_events ?? telemetry?.analytics?.row_counts?.outcome_events;
  return rowCount ? `${rowCount} outcome row` : "memory pending";
}

function deliveryFallbackForScenario(_scenario: DemoScenario) {
  return {
    guestMessage: "Waiting for Gemini to emit a guest-app payload for this request.",
    guestPrimary: "Acknowledge",
    guestSecondary: "Wait",
    workerMessage: "Waiting for Gemini to emit a worker task for this request.",
    workerPrimary: "Acknowledge",
    workerSecondary: "Request detail",
    target: "custom request",
  };
}

function dispatchForChannel(dispatches: DeliveryDispatch[], channel: string) {
  return dispatches.find((dispatch) => dispatch.channel === channel);
}

function deliveryStatusLabel(aiPhase: AiParkPhase, dispatch?: DeliveryDispatch) {
  if (dispatch?.response?.applied) return "applied";
  if (dispatch?.response?.acknowledgedCount || dispatch?.response?.state === "observed") return "observed";
  if (dispatch?.status) return dispatch.status;
  if (aiPhase === "running") return "delivering";
  if (aiPhase === "complete") return "sent";
  return "ready";
}

function RuntimeProofBadge({
  runtimeLabel,
  runtimeModel,
  runtimeGate,
  runtimeMemory,
  isLive,
  fallbackReason,
}: {
  runtimeLabel: string;
  runtimeModel: string;
  runtimeGate: string;
  runtimeMemory: string;
  isLive: boolean;
  fallbackReason?: string | null;
}) {
  const tone = isLive ? "border-emerald-300/55 bg-emerald-950/82 text-emerald-50" : fallbackReason ? "border-amber-300/55 bg-amber-950/82 text-amber-50" : "border-cyan-300/45 bg-slate-950/86 text-cyan-50";
  return (
    <div className={`pointer-events-none absolute left-3 top-3 z-50 w-[min(20rem,calc(100%-1.5rem))] rounded-lg border p-2.5 shadow-2xl backdrop-blur ${tone}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[9px] font-black uppercase tracking-widest opacity-80">Runtime proof</div>
        <span className={`rounded px-2 py-0.5 text-[8px] font-black uppercase ${isLive ? "bg-emerald-300 text-slate-950" : fallbackReason ? "bg-amber-300 text-slate-950" : "bg-cyan-300 text-slate-950"}`}>
          {isLive ? "Gemini" : fallbackReason ? "fallback" : "warming"}
        </span>
      </div>
      <div className="mt-1 truncate text-sm font-black leading-tight">{runtimeLabel}</div>
      <div className="mt-1 grid grid-cols-2 gap-1 text-[9px] font-black uppercase tracking-widest opacity-85">
        <span className="truncate">{runtimeModel}</span>
        <span className="truncate text-right">{runtimeGate}</span>
      </div>
      <div className="mt-1 truncate text-[10px] font-bold opacity-80">
        Memory: {runtimeMemory}
      </div>
    </div>
  );
}

function CascadeTimelineOverlay({ rows }: { rows: AiDemoStep[] }) {
  return (
    <div className="pointer-events-none absolute left-3 top-28 z-50 w-[min(20rem,calc(100%-1.5rem))] rounded-lg border border-white/25 bg-slate-950/82 p-2.5 text-slate-100 shadow-2xl backdrop-blur">
      <div className="text-[9px] font-black uppercase tracking-widest text-cyan-300">Operating cascade</div>
      <div className="mt-2 grid gap-1.5">
        {rows.map((row) => (
          <div key={row.id} className="grid grid-cols-[1rem_4.2rem_1fr] items-center gap-1.5">
            <span className={`h-2.5 w-2.5 rounded-full ${row.status === "done" ? "bg-emerald-300" : row.status === "active" ? "bg-cyan-300 park-command-pulse" : "bg-slate-700"}`} />
            <span className="text-[9px] font-black uppercase tracking-widest text-slate-300">{row.label}</span>
            <span className="truncate text-[10px] font-bold text-slate-100">{row.metric}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function LearningDeltaBadge({
  telemetry,
  runTelemetry,
  response,
}: {
  telemetry?: ProactiveRunTelemetry | null;
  runTelemetry?: RunTelemetry | null;
  response?: { takeRate?: number; reactiveFollowThroughRate?: number; score?: number; status?: string };
}) {
  const beforeTake = telemetry?.learning_proof?.run_1?.take_rate ?? response?.takeRate;
  const afterTake = telemetry?.learning_proof?.run_2?.expected_take_rate ?? telemetry?.learned_run?.best_prior?.prior_take_rate;
  const beforeFollow = telemetry?.learning_proof?.run_1?.follow_through_rate ?? response?.reactiveFollowThroughRate;
  const afterFollow = telemetry?.learning_proof?.run_2?.expected_follow_through_rate ?? telemetry?.learned_run?.best_prior?.prior_follow_through;
  const headline = telemetry?.learning_proof?.headline ?? runTelemetry?.outcome?.learning?.take_rate_signal ?? "Outcome response becomes the next plan bias.";
  const change = typeof beforeTake === "number" && typeof afterTake === "number" ? Math.round((afterTake - beforeTake) * 100) : undefined;

  return (
    <div className="pointer-events-none absolute bottom-3 left-1/2 z-50 hidden w-[min(24rem,calc(100%-46rem))] -translate-x-1/2 rounded-lg border border-violet-300/45 bg-violet-950/82 p-2.5 text-violet-50 shadow-2xl backdrop-blur xl:block">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[9px] font-black uppercase tracking-widest text-violet-200">Learning loop</div>
        <span className="rounded bg-violet-200 px-2 py-0.5 text-[8px] font-black uppercase text-violet-950">
          {change !== undefined ? `${change >= 0 ? "+" : ""}${change} pts` : "memory"}
        </span>
      </div>
      <div className="mt-1 truncate text-[11px] font-black">{headline}</div>
      <div className="mt-2 grid grid-cols-3 gap-1 text-center text-[9px] font-black uppercase tracking-widest">
        <div className="rounded bg-slate-950/55 px-2 py-1">
          <div className="text-violet-200">Run 1</div>
          <div className="mt-0.5 text-violet-50">{typeof beforeTake === "number" ? ratePct(beforeTake) : "--"}</div>
        </div>
        <div className="rounded bg-slate-950/55 px-2 py-1">
          <div className="text-violet-200">Learned</div>
          <div className="mt-0.5 text-violet-50">{typeof afterTake === "number" ? ratePct(afterTake) : "stored"}</div>
        </div>
        <div className="rounded bg-slate-950/55 px-2 py-1">
          <div className="text-violet-200">Follow</div>
          <div className="mt-0.5 text-violet-50">{typeof afterFollow === "number" ? ratePct(afterFollow) : typeof beforeFollow === "number" ? ratePct(beforeFollow) : "--"}</div>
        </div>
      </div>
    </div>
  );
}

function BeforeAfterReplayToggle({
  value,
  onChange,
  hasAction,
}: {
  value: "before" | "after";
  onChange: (value: "before" | "after") => void;
  hasAction: boolean;
}) {
  return (
    <div className="pointer-events-auto absolute left-1/2 top-3 z-50 flex -translate-x-1/2 rounded-lg border border-white/25 bg-slate-950/84 p-1 shadow-2xl backdrop-blur">
      {(["before", "after"] as const).map((item) => (
        <button
          key={item}
          type="button"
          disabled={!hasAction && item === "after"}
          onClick={() => onChange(item)}
          className={`rounded px-3 py-1.5 text-[10px] font-black uppercase tracking-widest transition disabled:cursor-not-allowed disabled:text-slate-600 ${
            value === item ? "bg-cyan-300 text-slate-950" : "text-slate-300 hover:bg-slate-800"
          }`}
        >
          {item === "before" ? "Before agent" : "After action"}
        </button>
      ))}
    </div>
  );
}

function StateMutationBadge({
  source,
  routes,
  staffMoves,
  hvacZones,
  dispatchCount,
  response,
}: {
  source: MapPoint;
  routes: RouteCue[];
  staffMoves: CustomActionOverlay["staffMoves"];
  hvacZones: CustomActionOverlay["hvacZones"];
  dispatchCount: number;
  response?: { takeRate?: number; reactiveFollowThroughRate?: number; score?: number; status?: string };
}) {
  const topRoute = routes[0];
  const takeRate = response?.takeRate;
  const follow = response?.reactiveFollowThroughRate;
  return (
    <div className="pointer-events-none absolute right-[23rem] top-3 z-50 hidden w-[min(20rem,calc(100%-46rem))] rounded-lg border border-emerald-300/45 bg-emerald-950/82 p-2.5 text-emerald-50 shadow-2xl backdrop-blur xl:block">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[9px] font-black uppercase tracking-widest text-emerald-200">Park state mutation</div>
        <span className="rounded bg-emerald-300 px-2 py-0.5 text-[8px] font-black uppercase text-slate-950">{dispatchCount || 0} actions</span>
      </div>
      <div className="mt-2 grid gap-1 text-[10px] font-bold leading-snug">
        <div className="truncate">Issue zone: {source.label} marked constrained</div>
        <div className="truncate">Guest flow: {topRoute ? `${topRoute.destination}${typeof topRoute.share === "number" ? ` ${Math.round(topRoute.share * 100)}%` : ""}` : "waiting for route"}</div>
        <div className="truncate">Workers: {staffMoves.length ? `${staffMoves[0].count ?? 1} ${staffMoves[0].role} moved` : "no worker move"}</div>
        <div className="truncate">Controls: {hvacZones.length ? `${hvacZones.length} comfort zone${hvacZones.length === 1 ? "" : "s"}` : "receiver controls applied as available"}</div>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-1 text-center text-[9px] font-black uppercase tracking-widest">
        <div className="rounded bg-slate-950/55 px-2 py-1">
          <div className="text-emerald-200">Take</div>
          <div>{typeof takeRate === "number" ? ratePct(takeRate) : "--"}</div>
        </div>
        <div className="rounded bg-slate-950/55 px-2 py-1">
          <div className="text-emerald-200">Follow</div>
          <div>{typeof follow === "number" ? ratePct(follow) : "--"}</div>
        </div>
      </div>
    </div>
  );
}

function domainKey(value: unknown) {
  const key = String(value ?? "").toLowerCase();
  if (["ride", "food", "staff", "medical", "crowd", "energy", "equipment"].includes(key)) return key;
  return "operations";
}

function visualDomainFor({
  domain,
  operatorCommand,
  scenarioKey,
  incidentType,
}: {
  domain: unknown;
  operatorCommand?: string;
  scenarioKey: ScenarioKey;
  incidentType?: string;
}) {
  const explicit = domainKey(domain);
  if (explicit !== "operations") return explicit;
  const text = `${operatorCommand ?? ""} ${incidentType ?? ""}`.toLowerCase();
  if (/(medical|first aid|faint|injur|wheelchair|accessib|handicapped)/.test(text)) return "medical";
  if (/(smoke|fire|sparking|electrical|gas|controller|missed heartbeat|fog machine|technician)/.test(text)) return "equipment";
  if (/(hvac|temperature|comfort|too hot|too cold|energy|load shed)/.test(text)) return "energy";
  if (/(panic|crowd|bottleneck|evac|fight|security|congestion)/.test(text)) return "crowd";
  if (/(called out|staff break|certified coverage|understaff|staff shortage|worker shortage|callout|labor gap)/.test(text)) return "staff";
  if (/(food|kitchen|restaurant|mobile order|pickup|inventory)/.test(text)) return "food";
  if (/(ride|coaster|queue|attraction|down)/.test(text)) return "ride";
  if (/(staff|worker|understaff|shortage|callout|break)/.test(text)) return "staff";
  if (scenarioKey === "food_spike") return "food";
  if (scenarioKey === "staff_shortage") return "staff";
  if (scenarioKey === "storm_response") return "energy";
  return "ride";
}

function DomainPhysicalEffects({
  domain,
  showAfterState,
  beforeAfterLine,
  dispatchTotal,
  aiFocus,
  customActionOverlay,
}: {
  domain: unknown;
  showAfterState: boolean;
  beforeAfterLine: string;
  dispatchTotal: number;
  aiFocus: ReturnType<typeof scenarioMapFocus>;
  customActionOverlay: CustomActionOverlay;
}) {
  const key = domainKey(domain);
  const activeColor =
    key === "medical" ? "#06b6d4" :
    key === "equipment" ? "#f97316" :
    key === "crowd" ? "#8b5cf6" :
    key === "food" ? "#f59e0b" :
    key === "staff" ? "#10b981" :
    key === "energy" ? "#38bdf8" :
    key === "ride" ? "#ef4444" :
    "#0ea5e9";
  const reliefColor = showAfterState ? "#10b981" : activeColor;
  const statusText = showAfterState ? "Action applied" : "Pressure detected";

  if (key === "medical") {
    const path = "M95 584 C235 550 384 516 510 500";
    return (
      <g data-testid="domain-visual-medical">
        <path d={path} stroke="#083344" strokeWidth="18" strokeLinecap="round" fill="none" opacity="0.2" />
        <path className="park-flow-line" d={path} stroke={reliefColor} strokeWidth="8" strokeLinecap="round" fill="none" opacity="0.9" />
        <circle className="park-node-pulse-svg" cx="516" cy="520" r={showAfterState ? "34" : "48"} fill={reliefColor} opacity="0.22" />
        <circle cx="516" cy="520" r="18" fill="#ecfeff" stroke={reliefColor} strokeWidth="5" />
        <text x="516" y="524" textAnchor="middle" fill="#0e7490" fontSize="14" fontWeight="900">+</text>
        <g transform="translate(548 492)">
          <rect width="190" height="48" rx="10" fill="#ecfeff" stroke={reliefColor} strokeWidth="3" />
          <text x="11" y="17" fill="#155e75" fontSize="10" fontWeight="900">Medical route protected</text>
          <text x="11" y="33" fill="#155e75" fontSize="9" fontWeight="800">{beforeAfterLine.slice(0, 34)}</text>
        </g>
      </g>
    );
  }

  if (key === "crowd") {
    const routes = [
      "M570 290 C500 252 395 272 280 350",
      "M570 290 C520 376 410 438 330 478",
      "M570 290 C492 328 430 370 438 486",
    ];
    return (
      <g data-testid="domain-visual-crowd">
        <circle className={showAfterState ? "" : "park-node-pulse-svg"} cx="570" cy="290" r={showAfterState ? "42" : "70"} fill={showAfterState ? "#10b981" : activeColor} opacity={showAfterState ? "0.14" : "0.2"} />
        {routes.map((path, index) => (
          <path key={path} className={showAfterState ? "park-flow-line" : ""} d={path} stroke={index === 0 ? "#8b5cf6" : "#22d3ee"} strokeWidth={showAfterState ? "7" : "4"} strokeLinecap="round" fill="none" opacity={showAfterState ? "0.84" : "0.42"} strokeDasharray={showAfterState ? undefined : "10 12"} />
        ))}
        <g transform="translate(604 254)">
          <rect width="174" height="48" rx="10" fill="#f5f3ff" stroke={reliefColor} strokeWidth="3" />
          <text x="11" y="17" fill="#5b21b6" fontSize="10" fontWeight="900">Crowd dispersal active</text>
          <text x="11" y="33" fill="#5b21b6" fontSize="9" fontWeight="800">{beforeAfterLine.slice(0, 32)}</text>
        </g>
      </g>
    );
  }

  if (key === "energy") {
    const zones = [
      { x: 270, y: 190, label: "Indoor" },
      { x: 530, y: 345, label: "Arcade" },
      { x: 502, y: 344, label: "HVAC" },
    ];
    return (
      <g data-testid="domain-visual-energy">
        {zones.map((zone, index) => (
          <g key={zone.label}>
            <circle className="park-node-pulse-svg" cx={zone.x} cy={zone.y} r={showAfterState ? 36 + index * 3 : 50 + index * 3} fill={index === 2 ? "#f59e0b" : "#38bdf8"} opacity={showAfterState ? "0.16" : "0.1"} />
            <circle cx={zone.x} cy={zone.y} r="15" fill="#eff6ff" stroke={index === 2 ? "#d97706" : "#0284c7"} strokeWidth="4" />
            <text x={zone.x} y={zone.y + 4} textAnchor="middle" fill="#075985" fontSize="8" fontWeight="900">{zone.label.slice(0, 4)}</text>
          </g>
        ))}
        <g transform="translate(548 312)">
          <rect width="180" height="48" rx="10" fill="#eff6ff" stroke="#38bdf8" strokeWidth="3" />
          <text x="11" y="17" fill="#075985" fontSize="10" fontWeight="900">Comfort controls changed</text>
          <text x="11" y="33" fill="#075985" fontSize="9" fontWeight="800">{beforeAfterLine.slice(0, 32)}</text>
        </g>
      </g>
    );
  }

  if (key === "food") {
    return (
      <g data-testid="domain-visual-food">
        <circle className={showAfterState ? "" : "park-node-pulse-svg"} cx="690" cy="505" r={showAfterState ? "46" : "64"} fill={showAfterState ? "#10b981" : "#f59e0b"} opacity={showAfterState ? "0.14" : "0.22"} />
        <path d="M690 505 C590 540 450 520 330 478" stroke="#78350f" strokeWidth="13" strokeLinecap="round" fill="none" opacity="0.16" />
        <path className={showAfterState ? "park-flow-line" : ""} d="M690 505 C590 540 450 520 330 478" stroke={showAfterState ? "#10b981" : "#f59e0b"} strokeWidth={showAfterState ? "7" : "5"} strokeLinecap="round" fill="none" opacity="0.9" strokeDasharray={showAfterState ? undefined : "10 12"} />
        <path d="M664 468 L717 540 M718 468 L665 540" stroke={showAfterState ? "#10b981" : "#ef4444"} strokeWidth="8" strokeLinecap="round" opacity={showAfterState ? "0.45" : "0.78"} />
        <g transform="translate(366 502)">
          <rect width="184" height="48" rx="10" fill="#fffbeb" stroke={reliefColor} strokeWidth="3" />
          <text x="11" y="17" fill="#78350f" fontSize="10" fontWeight="900">Mobile orders rerouted</text>
          <text x="11" y="33" fill="#78350f" fontSize="9" fontWeight="800">{beforeAfterLine.slice(0, 33)}</text>
        </g>
      </g>
    );
  }

  if (key === "staff") {
    const to = customActionOverlay.staffMoves[0]?.to ?? aiFocus.worker;
    const path = `M180 540 C290 470 398 454 ${to.x} ${to.y}`;
    return (
      <g data-testid="domain-visual-staff">
        <path d={path} stroke="#064e3b" strokeWidth="15" strokeLinecap="round" fill="none" opacity="0.16" />
        <path className={showAfterState ? "park-flow-line" : ""} d={path} stroke={reliefColor} strokeWidth="7" strokeLinecap="round" fill="none" opacity="0.9" strokeDasharray={showAfterState ? undefined : "10 12"} />
        {[0, 1, 2].map((index) => (
          <circle key={index} className="park-node-pulse-svg" cx={to.x - 20 + index * 18} cy={to.y + 24 - index * 3} r="7" fill="#10b981" />
        ))}
        <g transform={`translate(${Math.min(742, to.x + 24)} ${Math.max(92, to.y - 36)})`}>
          <rect width="178" height="48" rx="10" fill="#ecfdf5" stroke="#10b981" strokeWidth="3" />
          <text x="11" y="17" fill="#064e3b" fontSize="10" fontWeight="900">Staff redeployment</text>
          <text x="11" y="33" fill="#064e3b" fontSize="9" fontWeight="800">{beforeAfterLine.slice(0, 32)}</text>
        </g>
      </g>
    );
  }

  return (
    <g data-testid={`domain-visual-${key}`}>
      <circle className="park-node-pulse-svg" cx={customActionOverlay.source.x} cy={customActionOverlay.source.y} r={showAfterState ? "42" : "58"} fill={reliefColor} opacity="0.18" />
      <g transform={`translate(${Math.max(36, customActionOverlay.source.x - 78)} ${Math.max(78, customActionOverlay.source.y - 76)})`}>
        <rect width="184" height="48" rx="10" fill="#f8fafc" stroke={reliefColor} strokeWidth="3" />
        <text x="11" y="17" fill="#0f172a" fontSize="10" fontWeight="900">{statusText}</text>
        <text x="11" y="33" fill="#334155" fontSize="9" fontWeight="800">{dispatchTotal} dispatches / {beforeAfterLine.slice(0, 20)}</text>
      </g>
    </g>
  );
}

function ReceiverTray({
  scenario: _scenario,
  aiPhase,
  dispatches,
  response,
}: {
  scenario: DemoScenario;
  aiPhase: AiParkPhase;
  dispatches: DeliveryDispatch[];
  response?: { takeRate?: number; positiveResponseRate?: number; reactiveFollowThroughRate?: number; score?: number; status?: string };
}) {
  const guestDispatch = dispatchForChannel(dispatches, "guest_app");
  const workerDispatch = dispatchForChannel(dispatches, "worker_device");
  const equipmentDispatch = dispatchForChannel(dispatches, "equipment_controller");
  const isLive = aiPhase !== "idle";
  const guestMetric = guestDispatch?.response?.takeRate ?? response?.takeRate;
  const followMetric = guestDispatch?.response?.reactiveFollowThroughRate ?? workerDispatch?.response?.reactiveFollowThroughRate ?? response?.reactiveFollowThroughRate;
  const workerAck = workerDispatch?.response?.acknowledgedCount ?? workerDispatch?.response?.sampleSize;
  const equipmentMessage = equipmentDispatch ? dispatchBody(equipmentDispatch) : "Waiting for Gemini to emit an equipment-control payload.";
  const statusClass = aiPhase === "complete" ? "bg-emerald-300 text-slate-950" : aiPhase === "running" ? "bg-cyan-300 text-slate-950 park-command-pulse" : "bg-slate-800 text-slate-300";
  const cards = [
    {
      key: "guest",
      label: "Guest app",
      status: deliveryStatusLabel(aiPhase, guestDispatch),
      title: guestDispatch ? dispatchBody(guestDispatch) : "Waiting for Gemini to emit a guest-app payload.",
      metric: guestMetric ? `${ratePct(guestMetric)} take` : isLive ? "sent" : "ready",
      tone: "border-cyan-300/40 bg-cyan-950/80 text-cyan-50",
    },
    {
      key: "worker",
      label: "Worker task",
      status: deliveryStatusLabel(aiPhase, workerDispatch),
      title: workerDispatch ? dispatchBody(workerDispatch) : "Waiting for Gemini to emit a worker task.",
      metric: workerAck ? `${workerAck} ack` : followMetric ? `${ratePct(followMetric)} follow` : isLive ? "assigned" : "ready",
      tone: "border-emerald-300/40 bg-emerald-950/80 text-emerald-50",
    },
    {
      key: "equipment",
      label: "Equipment control",
      status: deliveryStatusLabel(aiPhase, equipmentDispatch),
      title: equipmentMessage,
      metric: equipmentDispatch?.response?.applied ? "applied" : isLive ? "commanded" : "ready",
      tone: "border-amber-300/40 bg-amber-950/80 text-amber-50",
    },
  ];

  return (
    <div className="pointer-events-auto absolute bottom-3 right-3 z-50 grid w-[min(22rem,calc(100%-1.5rem))] gap-2">
      {cards.map((card) => (
        <article key={card.key} className={`rounded-lg border p-2.5 shadow-2xl backdrop-blur ${card.tone}`}>
          <div className="flex items-center justify-between gap-2">
            <div className="text-[10px] font-black uppercase tracking-widest opacity-80">{card.label}</div>
            <span className={`rounded px-2 py-1 text-[9px] font-black uppercase ${statusClass}`}>{card.status}</span>
          </div>
          <div className="mt-1 line-clamp-1 text-xs font-black leading-snug">{card.title}</div>
          <div className="mt-1 flex items-center justify-between gap-2 text-[10px] font-black uppercase tracking-widest opacity-80">
            <span>{card.metric}</span>
            <span>{card.key === "guest" ? "mobile" : card.key === "worker" ? "staff" : "control"}</span>
          </div>
        </article>
      ))}
    </div>
  );
}

function CompactReceiverDemo({
  scenario,
  aiPhase,
  dispatches,
  response,
  onReceiverAck,
}: {
  scenario: DemoScenario;
  aiPhase: AiParkPhase;
  dispatches: DeliveryDispatch[];
  response?: { takeRate?: number; positiveResponseRate?: number; reactiveFollowThroughRate?: number; score?: number; status?: string };
  onReceiverAck?: (dispatch: DeliveryDispatch | undefined, actor: string, choice: string) => void;
}) {
  const fallback = deliveryFallbackForScenario(scenario);
  const guestDispatch = dispatchForChannel(dispatches, "guest_app");
  const workerDispatch = dispatchForChannel(dispatches, "worker_device");
  const [guestChoice, setGuestChoice] = useState<string | null>(null);
  const [workerChoice, setWorkerChoice] = useState<string | null>(null);
  const guestMetric = guestDispatch?.response?.takeRate ?? response?.takeRate;
  const workerAck = workerDispatch?.response?.acknowledgedCount ?? workerDispatch?.response?.sampleSize;

  const phones = [
    {
      key: "guest",
      label: "Guest phone",
      status: deliveryStatusLabel(aiPhase, guestDispatch),
      message: guestDispatch ? dispatchBody(guestDispatch) : fallback.guestMessage,
      primary: fallback.guestPrimary,
      secondary: fallback.guestSecondary,
      choice: guestChoice,
      dispatch: guestDispatch,
      canAct: Boolean(guestDispatch) && aiPhase !== "idle",
      setChoice: (choice: string) => {
        setGuestChoice(choice);
        onReceiverAck?.(guestDispatch, "guest_app", choice);
      },
      metric: guestMetric ? `${ratePct(guestMetric)} take` : aiPhase === "idle" ? "--" : "sent",
      tone: "border-cyan-300/40 bg-cyan-950/90 text-cyan-50",
    },
    {
      key: "worker",
      label: "Worker phone",
      status: deliveryStatusLabel(aiPhase, workerDispatch),
      message: workerDispatch ? dispatchBody(workerDispatch) : fallback.workerMessage,
      primary: fallback.workerPrimary,
      secondary: fallback.workerSecondary,
      choice: workerChoice,
      dispatch: workerDispatch,
      canAct: Boolean(workerDispatch) && aiPhase !== "idle",
      setChoice: (choice: string) => {
        setWorkerChoice(choice);
        onReceiverAck?.(workerDispatch, "worker_device", choice);
      },
      metric: workerAck ? `${workerAck} ack` : aiPhase === "idle" ? "--" : "sent",
      tone: "border-amber-300/40 bg-amber-950/90 text-amber-50",
    },
  ];

  return (
    <div className="pointer-events-auto absolute bottom-3 left-3 z-50 grid w-[min(22rem,calc(100%-24rem))] gap-2 max-lg:hidden">
      {phones.map((phone) => (
        <article key={phone.key} className={`rounded-2xl border-[5px] border-slate-950 p-1 shadow-2xl ${phone.tone}`}>
          <div className="rounded-xl border border-white/10 bg-slate-950/45 p-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[10px] font-black uppercase tracking-widest">{phone.label}</div>
              <span className="rounded bg-white/90 px-2 py-1 text-[9px] font-black uppercase text-slate-950">{phone.status}</span>
            </div>
            <div className="mt-1 line-clamp-2 text-[11px] font-black leading-snug">{phone.message}</div>
            <div className="mt-2 grid grid-cols-[1fr_auto] gap-1.5">
              <button
                type="button"
                disabled={!phone.canAct}
                onClick={() => phone.setChoice(phone.primary)}
                className={`rounded px-2 py-1.5 text-[10px] font-black transition disabled:cursor-not-allowed disabled:bg-white/25 disabled:text-white/45 ${phone.choice === phone.primary ? "bg-emerald-300 text-slate-950" : "bg-white/90 text-slate-950"}`}
              >
                {phone.primary}
              </button>
              <button
                type="button"
                disabled={!phone.canAct}
                onClick={() => phone.setChoice(phone.secondary)}
                className={`rounded border px-2 py-1.5 text-[10px] font-black transition disabled:cursor-not-allowed disabled:border-white/10 disabled:text-white/35 ${phone.choice === phone.secondary ? "border-emerald-200 bg-emerald-300 text-slate-950" : "border-white/30 text-white"}`}
              >
                {phone.secondary}
              </button>
            </div>
            <div className="mt-1 flex items-center justify-between text-[9px] font-black uppercase tracking-widest opacity-80">
              <span>{phone.choice ?? (aiPhase === "complete" ? phone.primary : "waiting")}</span>
              <span>{phone.metric}</span>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

function PhoneDeliveryDemo({
  scenario,
  aiPhase,
  dispatches,
  response,
}: {
  scenario: DemoScenario;
  aiPhase: AiParkPhase;
  dispatches: DeliveryDispatch[];
  response?: { takeRate?: number; positiveResponseRate?: number; reactiveFollowThroughRate?: number; score?: number; status?: string };
}) {
  const fallback = deliveryFallbackForScenario(scenario);
  const guestDispatch = dispatchForChannel(dispatches, "guest_app");
  const workerDispatch = dispatchForChannel(dispatches, "worker_device");
  const [guestChoice, setGuestChoice] = useState<string | null>(null);
  const [workerChoice, setWorkerChoice] = useState<string | null>(null);
  const isLive = aiPhase !== "idle";
  const guestMessage = guestDispatch ? dispatchBody(guestDispatch) : fallback.guestMessage;
  const workerMessage = workerDispatch ? dispatchBody(workerDispatch) : fallback.workerMessage;
  const guestMetric = guestDispatch?.response?.takeRate ?? response?.takeRate;
  const workerAck = workerDispatch?.response?.acknowledgedCount ?? workerDispatch?.response?.sampleSize;
  const followMetric = guestDispatch?.response?.reactiveFollowThroughRate ?? workerDispatch?.response?.reactiveFollowThroughRate ?? response?.reactiveFollowThroughRate;
  const statusClass = aiPhase === "complete" ? "bg-emerald-100 text-emerald-900" : aiPhase === "running" ? "bg-cyan-100 text-cyan-950 park-command-pulse" : "bg-stone-100 text-stone-700";
  const hasChoice = Boolean(guestChoice || workerChoice || aiPhase === "complete");

  return (
    <div className="pointer-events-auto relative z-40 mx-auto mt-[calc(100vh+1rem)] max-w-5xl px-4 pb-12">
      <div className="grid items-end gap-3 md:grid-cols-[1fr_12rem_1fr]">
        <article className="rounded-[1.75rem] border-[6px] border-slate-950 bg-slate-950 p-2 shadow-2xl shadow-stone-950/30">
          <div className="overflow-hidden rounded-[1.25rem] bg-cyan-50 text-slate-950">
            <div className="flex items-center justify-between bg-cyan-900 px-4 py-3 text-cyan-50">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Guest phone</div>
                <div className="text-sm font-black">Park app message</div>
              </div>
              <span className={`rounded px-2 py-1 text-[10px] font-black uppercase ${statusClass}`}>{deliveryStatusLabel(aiPhase, guestDispatch)}</span>
            </div>
            <div className="space-y-3 p-4">
              <div className="rounded-lg border border-cyan-200 bg-white p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-700">Delivered action</div>
                <div className="mt-2 text-sm font-black leading-snug text-slate-950">{guestMessage}</div>
                <div className="mt-2 text-[11px] font-bold text-slate-500">Target: {guestDispatch?.payload?.targetZone ?? fallback.target}</div>
              </div>
              <div className="grid grid-cols-[1fr_auto] gap-2">
                <button
                  type="button"
                  onClick={() => setGuestChoice(fallback.guestPrimary)}
                  className={`rounded px-3 py-2 text-xs font-black shadow ${guestChoice === fallback.guestPrimary ? "bg-emerald-600 text-white" : "bg-cyan-700 text-white"}`}
                >
                  {fallback.guestPrimary}
                </button>
                <button
                  type="button"
                  onClick={() => setGuestChoice(fallback.guestSecondary)}
                  className={`rounded border px-3 py-2 text-xs font-black ${guestChoice === fallback.guestSecondary ? "border-emerald-300 bg-emerald-50 text-emerald-900" : "border-cyan-200 bg-white text-cyan-900"}`}
                >
                  {fallback.guestSecondary}
                </button>
              </div>
              <div className="rounded bg-white/75 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-cyan-900">
                Guest choice: {guestChoice ?? (aiPhase === "complete" ? fallback.guestPrimary : "waiting")}
              </div>
              <div className="grid grid-cols-3 gap-2 text-center text-[10px] font-black">
                <div className="rounded bg-cyan-100 p-2">
                  <div className="text-cyan-700">Take</div>
                  <div className="mt-1 text-slate-950">{guestMetric ? ratePct(guestMetric) : isLive ? "sent" : "--"}</div>
                </div>
                <div className="rounded bg-emerald-100 p-2">
                  <div className="text-emerald-700">Follow</div>
                  <div className="mt-1 text-slate-950">{followMetric ? ratePct(followMetric) : isLive ? "watch" : "--"}</div>
                </div>
                <div className="rounded bg-slate-100 p-2">
                  <div className="text-slate-500">Channel</div>
                  <div className="mt-1 text-slate-950">app</div>
                </div>
              </div>
            </div>
          </div>
        </article>

        <div className="relative hidden self-center md:block">
          <div className="absolute left-[-4.5rem] right-[-4.5rem] top-1/2 h-2 -translate-y-1/2 rounded bg-slate-950/35" />
          <div className={`relative rounded-lg border border-white/70 bg-white/95 p-3 text-center shadow-xl shadow-stone-950/20 ${aiPhase === "running" ? "park-action-chip" : ""}`}>
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Action bus</div>
            <div className="mt-1 text-lg font-black text-slate-950">{dispatches.length || (isLive ? 2 : 0)}</div>
            <div className="text-[10px] font-black uppercase text-slate-500">payloads</div>
            <div className="mt-2 grid grid-cols-3 gap-1 text-[9px] font-black uppercase">
              {["send", "choose", "measure"].map((step, index) => (
                <div key={step} className={`rounded px-1.5 py-1 ${aiPhase === "idle" && index > 0 && !(index === 1 && hasChoice) ? "bg-stone-100 text-stone-400" : aiPhase === "running" && index === 0 ? "bg-cyan-100 text-cyan-900" : index === 1 && hasChoice ? "bg-emerald-100 text-emerald-900" : "bg-emerald-100 text-emerald-900"}`}>
                  {step}
                </div>
              ))}
            </div>
          </div>
        </div>

        <article className="rounded-[1.75rem] border-[6px] border-slate-950 bg-slate-950 p-2 shadow-2xl shadow-stone-950/30">
          <div className="overflow-hidden rounded-[1.25rem] bg-amber-50 text-slate-950">
            <div className="flex items-center justify-between bg-amber-900 px-4 py-3 text-amber-50">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Worker phone</div>
                <div className="text-sm font-black">Staff task card</div>
              </div>
              <span className={`rounded px-2 py-1 text-[10px] font-black uppercase ${statusClass}`}>{deliveryStatusLabel(aiPhase, workerDispatch)}</span>
            </div>
            <div className="space-y-3 p-4">
              <div className="rounded-lg border border-amber-200 bg-white p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-amber-700">Assigned action</div>
                <div className="mt-2 text-sm font-black leading-snug text-slate-950">{workerMessage}</div>
                <div className="mt-2 text-[11px] font-bold text-slate-500">Endpoint: {workerDispatch?.endpoint ?? "/api/actions/worker-task"}</div>
              </div>
              <div className="grid grid-cols-[1fr_auto] gap-2">
                <button
                  type="button"
                  onClick={() => setWorkerChoice(fallback.workerPrimary)}
                  className={`rounded px-3 py-2 text-xs font-black shadow ${workerChoice === fallback.workerPrimary ? "bg-emerald-600 text-white" : "bg-amber-700 text-white"}`}
                >
                  {fallback.workerPrimary}
                </button>
                <button
                  type="button"
                  onClick={() => setWorkerChoice(fallback.workerSecondary)}
                  className={`rounded border px-3 py-2 text-xs font-black ${workerChoice === fallback.workerSecondary ? "border-emerald-300 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-white text-amber-900"}`}
                >
                  {fallback.workerSecondary}
                </button>
              </div>
              <div className="rounded bg-white/75 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-amber-900">
                Worker choice: {workerChoice ?? (aiPhase === "complete" ? fallback.workerPrimary : "waiting")}
              </div>
              <div className="grid grid-cols-3 gap-2 text-center text-[10px] font-black">
                <div className="rounded bg-amber-100 p-2">
                  <div className="text-amber-700">Ack</div>
                  <div className="mt-1 text-slate-950">{workerAck ?? (isLive ? "sent" : "--")}</div>
                </div>
                <div className="rounded bg-emerald-100 p-2">
                  <div className="text-emerald-700">Follow</div>
                  <div className="mt-1 text-slate-950">{followMetric ? ratePct(followMetric) : isLive ? "watch" : "--"}</div>
                </div>
                <div className="rounded bg-slate-100 p-2">
                  <div className="text-slate-500">Channel</div>
                  <div className="mt-1 text-slate-950">staff</div>
                </div>
              </div>
            </div>
          </div>
        </article>
      </div>
    </div>
  );
}

export function VisualParkBoard({
  flow,
  scenario,
  isConnected,
  isRunning,
  runTelemetry,
  parkState,
  proactiveRunTelemetry,
  signalTriage,
  operatorCommand,
  operatorCommandResult,
  isRunningProactive = false,
  visualStepIndex = 0,
  compact = false,
  showCompactPanels = true,
  showOverlayControls = true,
  mapLayer,
  onMapLayerChange,
  showLabels,
  onShowLabelsChange,
  showDetails,
  onShowDetailsChange,
  selectedMapItem,
  agentMapGrounding,
  agentImpactReplay,
  onMapSelectionChange,
  onReceiverAck,
}: {
  flow: GuestFlow;
  scenario: DemoScenario;
  isConnected: boolean;
  isRunning: boolean;
  runTelemetry: RunTelemetry | null;
  parkState?: ParkState;
  proactiveRunTelemetry?: ProactiveRunTelemetry | null;
  signalTriage?: SignalTriageResult | null;
  operatorCommand?: string;
  operatorCommandResult?: OperatorCommandResponse | null;
  isRunningProactive?: boolean;
  visualStepIndex?: number;
  compact?: boolean;
  showCompactPanels?: boolean;
  showOverlayControls?: boolean;
  mapLayer?: MapLayer;
  onMapLayerChange?: (layer: MapLayer) => void;
  showLabels?: boolean;
  onShowLabelsChange?: (value: boolean) => void;
  showDetails?: boolean;
  onShowDetailsChange?: (value: boolean) => void;
  selectedMapItem?: MapSelection | null;
  agentMapGrounding?: AgentMapGrounding | null;
  agentImpactReplay?: AgentImpactReplay | null;
  onMapSelectionChange?: (selection: MapSelection) => void;
  onReceiverAck?: (dispatch: DeliveryDispatch | undefined, actor: string, choice: string) => void;
}) {
  const [agentReplayPhase, setAgentReplayPhase] = useState<ImpactReplayPhase>("action");
  const replayState = agentImpactReplay?.state;
  const replayAfterActive = Boolean(agentImpactReplay && agentReplayPhase === "after" && replayState?.guestFlow);
  const mapFlow = replayAfterActive && replayState?.guestFlow ? replayState.guestFlow : flow;
  const mapParkState = replayAfterActive && replayState ? replayState : parkState;
  const rides = sortedByRisk(mapFlow.rides, (ride) => ride.waitMins + ride.queueGuests / 20 + ride.downtimeRisk / 4, 5);
  const busiestZone = sortedByRisk(mapFlow.zones, (zone) => zone.density, 1)[0];
  const totalQueue = rides.reduce((sum, ride) => sum + ride.queueGuests, 0);
  const avgWait = Math.round(rides.reduce((sum, ride) => sum + ride.waitMins, 0) / Math.max(1, rides.length));
  const parkClock = mapParkState?.simTime ? `${String(mapParkState.simTime.hour).padStart(2, "0")}:${String(mapParkState.simTime.minute).padStart(2, "0")}` : "--";
  const metricPreview = [
    { label: "Total queue", value: totalQueue.toLocaleString(), detail: "Current queue guests from live park state.", tone: totalQueue > 1800 ? "risk" : "watch" },
    { label: "Avg wait", value: `${avgWait}m`, detail: "Computed from current attraction waits.", tone: avgWait > 35 ? "risk" : "watch" },
    { label: "Busiest zone", value: busiestZone?.name ?? "Live park", detail: `${busiestZone?.density ?? 0}% density from current state.`, tone: (busiestZone?.density ?? 0) > 82 ? "risk" : "ok" },
  ] as const;
  const actionPreview = runTelemetry?.planner?.selected_action
    ? [{
        owner: runTelemetry.planner.selected_action.owner ?? "Runtime agent",
        action: runTelemetry.planner.selected_action.label ?? "Custom action",
      }]
    : [];
  const loadedPhysicalMap = mapParkState?.physicalMap ?? DEFAULT_PHYSICAL_MAP;
  const operatingClock = mapParkState?.operatingClock;
  const activeShowtimes = operatingClock?.eventSchedule.activeEvents ?? [];
  const nextShowtime = operatingClock?.eventSchedule.nextEvent;
  const showtimeRisk = operatingClock?.eventSchedule.eventTrafficRiskPct ?? nextShowtime?.trafficRiskPct ?? 0;
  const accessFairness = operatingClock?.accessFairness;
  const physicalMap: ParkPhysicalMap = {
    ...DEFAULT_PHYSICAL_MAP,
    ...loadedPhysicalMap,
    scale: loadedPhysicalMap.scale ?? DEFAULT_PHYSICAL_MAP.scale,
    landmarks: loadedPhysicalMap.landmarks ?? DEFAULT_PHYSICAL_MAP.landmarks,
    facilities: loadedPhysicalMap.facilities ?? DEFAULT_PHYSICAL_MAP.facilities,
    supportStations: loadedPhysicalMap.supportStations ?? DEFAULT_PHYSICAL_MAP.supportStations,
    queues: loadedPhysicalMap.queues ?? DEFAULT_PHYSICAL_MAP.queues,
    guestGroups: loadedPhysicalMap.guestGroups ?? DEFAULT_PHYSICAL_MAP.guestGroups,
    serviceRoutes: loadedPhysicalMap.serviceRoutes ?? DEFAULT_PHYSICAL_MAP.serviceRoutes,
    realismNotes: loadedPhysicalMap.realismNotes ?? DEFAULT_PHYSICAL_MAP.realismNotes,
  };
  const scaleLabel = `${physicalMap.scale.widthMeters}m x ${physicalMap.scale.heightMeters}m`;
  const [internalActiveLayer, setInternalActiveLayer] = useState<MapLayer>("attractions");
  const [zoom, setZoom] = useState(1);
  const [focus, setFocus] = useState(MAP_FOCUS_POINTS[0]);
  const [internalShowMapLabels, setInternalShowMapLabels] = useState(false);
  const [internalShowMapDetails, setInternalShowMapDetails] = useState(false);
  const [replayView, setReplayView] = useState<"before" | "after">("after");
  const [timeLens, setTimeLens] = useState<MapTimeLens>("now");
  const activeLayer = mapLayer ?? internalActiveLayer;
  const showMapLabels = showLabels ?? internalShowMapLabels;
  const showMapDetails = showDetails ?? internalShowMapDetails;
  const updateActiveLayer = (layer: MapLayer) => {
    setInternalActiveLayer(layer);
    onMapLayerChange?.(layer);
  };
  const updateShowMapLabels = (value: boolean) => {
    setInternalShowMapLabels(value);
    onShowLabelsChange?.(value);
  };
  const updateShowMapDetails = (value: boolean) => {
    setInternalShowMapDetails(value);
    onShowDetailsChange?.(value);
  };
  const updateAgentReplayPhase = (phase: ImpactReplayPhase) => {
    setAgentReplayPhase(phase);
    setReplayView(phase === "before" || phase === "baseline" ? "before" : "after");
    if (phase === "baseline") setTimeLens("future");
    if (phase === "after") setTimeLens("now");
  };
  const viewBox = viewBoxForFocus(focus, zoom);
  useEffect(() => {
    if (compact && activeLayer === "attractions" && !selectedMapItem) {
      setFocus(MAP_FOCUS_POINTS[0]);
      setZoom(1);
    }
  }, [activeLayer, compact, selectedMapItem]);
  useEffect(() => {
    if (!agentImpactReplay) return;
    setAgentReplayPhase("action");
    setReplayView("after");
    setTimeLens("now");
  }, [agentImpactReplay?.created_at, agentImpactReplay?.action_plan?.id]);
  const effectiveRunTelemetry = operatorCommandResult?.run_telemetry ?? runTelemetry;
  const operatorDispatches = operatorCommandResult?.run_telemetry?.delivery?.dispatches ?? [];
  const aiPhase = aiPhaseForMap(isRunning, isRunningProactive, Boolean(proactiveRunTelemetry || effectiveRunTelemetry || signalTriage || operatorCommandResult));
  const hasCustomContext = Boolean(effectiveRunTelemetry || proactiveRunTelemetry || signalTriage || operatorCommandResult || operatorCommand?.trim());
  const scenarioAiFocus = scenarioMapFocus(scenario.key);
  const operatorLandmarkIds = commandMentions(operatorCommand, ["food", "kitchen", "restaurant", "mobile order"])
    ? ["foodCourtA", "mainStreet", "firstAid"]
    : commandMentions(operatorCommand, ["medical", "faint", "first aid", "wheelchair", "accessibility", "handicapped"])
      ? ["firstAid", "mainStreet", "foodCourtA"]
      : commandMentions(operatorCommand, ["security", "panic", "evac", "fight"])
        ? ["frontGate", "mainStreet", "firstAid"]
        : undefined;
  const compactLandmarkIds = new Set(
    !hasCustomContext
      ? ["frontGate", "mainStreet", "foodCourtA", "indoorLaunch", "firstAid"]
      : operatorLandmarkIds
        ? operatorLandmarkIds
      : scenario.key === "food_spike"
      ? ["foodCourtA", "mainStreet", "firstAid"]
      : scenario.key === "staff_shortage"
        ? ["foodCourtA", "firstAid", "mainStreet"]
        : scenario.key === "storm_response"
          ? ["indoorLaunch", "theaterB", "arcade", "firstAid"]
          : ["dragonCoaster", "indoorLaunch", "firstAid"],
  );
  (agentMapGrounding?.landmark_ids ?? []).forEach((id) => compactLandmarkIds.add(id));
  const proof = scenarioProof(scenario, proactiveRunTelemetry, effectiveRunTelemetry);
  const showAiResponse = compact && aiPhase !== "idle";
  const showDetailedActionAnnotations = showAiResponse && showCompactPanels;
  const showDecisionPhase = showAiResponse && visualStepIndex >= 1;
  const showGovernPhase = showAiResponse && visualStepIndex >= 2;
  const showEmitPhase = showAiResponse && visualStepIndex >= 3;
  const showObservePhase = showAiResponse && visualStepIndex >= 4;
  const showLearnPhase = showAiResponse && visualStepIndex >= 5;
  const showAttractions = activeLayer === "overview" || activeLayer === "attractions";
  const showQueues = activeLayer === "overview" || activeLayer === "queues" || activeLayer === "signals" || selectedMapItem?.kind === "queue";
  const showGuests = activeLayer === "overview" || activeLayer === "guests" || selectedMapItem?.kind === "guest-group";
  const showSupport = activeLayer === "overview" || activeLayer === "support" || activeLayer === "operations" || selectedMapItem?.kind === "support-station";
  const showOperations = activeLayer === "overview" || activeLayer === "operations" || selectedMapItem?.kind === "facility";
  const showSignals = activeLayer === "signals";
  const showOperatingClockOverlay = Boolean(operatingClock) && (activeLayer === "overview" || activeLayer === "signals" || activeLayer === "operations" || compact);
  const showOperatingClockLabels = Boolean(operatingClock);
  const lifecycle = proactiveRunTelemetry?.lifecycle;
  const dispatches = signalTriage?.delivery?.dispatches?.length ? signalTriage.delivery.dispatches : operatorDispatches.length ? operatorDispatches : proactiveRunTelemetry?.delivery?.dispatches ?? effectiveRunTelemetry?.delivery?.dispatches ?? [];
  const deliveryResponse = signalTriage?.delivery?.response ?? operatorCommandResult?.run_telemetry?.delivery?.response ?? proactiveRunTelemetry?.delivery?.response ?? effectiveRunTelemetry?.delivery?.response;
  const guestDispatch = dispatchForChannel(dispatches, "guest_app");
  const workerDispatch = dispatchForChannel(dispatches, "worker_device");
  const equipmentDispatch = dispatchForChannel(dispatches, "equipment_controller");
  const customActionOverlay = buildCustomActionOverlay({ scenario, dispatches, operatorCommand, runTelemetry: effectiveRunTelemetry, proactiveRunTelemetry, operatorCommandResult });
  const cascadeRows = buildAiDemoSteps({ scenario, phase: aiPhase, activeStep: visualStepIndex, telemetry: proactiveRunTelemetry, runTelemetry: effectiveRunTelemetry });
  const hasOperatorIntent = Boolean(operatorCommand?.trim());
  const hasActionPayload = dispatches.length > 0 || Boolean(effectiveRunTelemetry || proactiveRunTelemetry || signalTriage || operatorCommandResult) || (hasOperatorIntent && visualStepIndex >= 2);
  const showAfterState = replayView === "after" && hasActionPayload;
  const showBeforeState = !showAfterState;
  const guestAcked = guestDispatch?.response?.state === "acknowledged" || Boolean(guestDispatch?.response?.choice);
  const workerAcked = workerDispatch?.response?.state === "acknowledged" || Boolean(workerDispatch?.response?.choice);
  const equipmentApplied = Boolean(equipmentDispatch?.response?.applied);
  const hasReceiverAck = guestAcked || workerAcked || equipmentApplied;
  const showLiveObservePhase = showObservePhase || hasReceiverAck;
  const showLiveLearnPhase = showLearnPhase || (guestAcked && workerAcked);
  const receiverAckLabel =
    guestAcked && workerAcked
      ? "Guest and worker acknowledged"
      : guestAcked
        ? `Guest chose ${guestDispatch?.response?.choice ?? "route"}`
        : workerAcked
          ? `Worker chose ${workerDispatch?.response?.choice ?? "task"}`
          : equipmentApplied
            ? "Equipment command applied"
            : "Receiver reaction pending";
  const stateImpact = lifecycle?.state_impact ?? operatorCommandResult?.run_telemetry?.outcome?.state_impact ?? operatorCommandResult?.outcome?.state_impact ?? proactiveRunTelemetry?.outcome?.state_impact ?? effectiveRunTelemetry?.outcome?.state_impact;
  const stateApplication = operatorCommandResult?.run_telemetry?.outcome?.application ?? operatorCommandResult?.outcome?.application ?? proactiveRunTelemetry?.outcome?.application ?? effectiveRunTelemetry?.outcome?.application;
  const visualDomain = visualDomainFor({
    domain: stateImpact?.domain,
    operatorCommand,
    scenarioKey: scenario.key,
    incidentType: customActionOverlay.incidentType,
  });
  const aiFocus = domainMapFocus(visualDomain, scenarioAiFocus);
  const movedGuests = showAfterState ? stateApplication?.movedGuests ?? Math.abs(stateImpact?.queued_guest_delta ?? 0) : 0;
  const densityDelta = showAfterState ? stateImpact?.density_delta ?? -8 : 0;
  const stateImpactLine = stateImpact?.headline ?? proof.after;
  const beforeAfterLine = stateImpact?.before && stateImpact?.after
    ? stateImpact.before_after_line ?? `Backlog ${stateImpact.before.food_backlog ?? "--"} -> ${stateImpact.after.food_backlog ?? "--"} / ETA ${stateImpact.before.food_eta ?? "--"}m -> ${stateImpact.after.food_eta ?? "--"}m`
    : aiFocus.relief;
  const dispatchTotal = lifecycle?.metrics?.dispatch_total ?? operatorCommandResult?.run_telemetry?.delivery?.summary?.total ?? proactiveRunTelemetry?.delivery?.summary?.total ?? dispatches.length;
  const takeRateLabel = typeof deliveryResponse?.takeRate === "number" ? `Take ${ratePct(deliveryResponse.takeRate)}` : "Take pending";
  const analyticsStatus = operatorCommandResult?.role_receipt?.bigquery?.status ?? effectiveRunTelemetry?.analytics?.status ?? proactiveRunTelemetry?.analytics?.status;
  const analyticsLabel = analyticsStatus ? `BigQuery ${cleanRuntimeLabel(analyticsStatus)}` : "BigQuery rows queued";
  const learnedBiasLabel =
    operatorCommandResult?.role_receipt?.learning_update?.next_plan_bias ??
    effectiveRunTelemetry?.outcome?.learning?.next_plan_bias ??
    runTelemetry?.outcome?.learning?.take_rate_signal ??
    proactiveRunTelemetry?.learning_proof?.next_plan_bias ??
    proactiveRunTelemetry?.lifecycle?.learning?.next_prompt ??
    "Outcome saved for next decision";
  const runtimeLabel = liveRuntimeLabel(proactiveRunTelemetry, effectiveRunTelemetry);
  const runtimeModel = liveModelLabel(proactiveRunTelemetry, effectiveRunTelemetry);
  const runtimeGate = liveGateLabel(proactiveRunTelemetry, effectiveRunTelemetry);
  const runtimeMemory = liveMemoryLabel(proactiveRunTelemetry, effectiveRunTelemetry);
  const runtimeProof = proactiveRunTelemetry?.runtime_proof;
  const runtimeIsLive = runtimeProof?.mode === "full_runtime" || effectiveRunTelemetry?.planner?.gemini_ready;
  const runtimeCalloutTone = runtimeIsLive ? "#10b981" : runtimeProof?.mode === "bounded_fallback" ? "#f59e0b" : "#0891b2";
  const layerStats = {
    attractions: physicalMap.landmarks.length,
    queues: physicalMap.queues.length,
    guests: physicalMap.guestGroups.length,
    support: physicalMap.supportStations.length,
    operations: physicalMap.facilities.length + physicalMap.serviceRoutes.length + physicalMap.supportStations.length,
    signals: mapFlow.zones.filter((zone) => zone.density >= 70).length + rides.filter((ride) => ride.status !== "normal").length,
  };
  const focusMapSelection = (label: string, x: number, y: number, nextZoom = 1.35) => {
    if (!compact) return;
    setFocus({ label, x, y, zoom: nextZoom });
    setZoom(nextZoom);
  };
  const selectMapItem = (selection: MapSelection) => {
    onMapSelectionChange?.(selection);
  };
  const selectedKey = selectedMapItem ? `${selectedMapItem.kind}:${selectedMapItem.id}` : "";
  const hasMapSelection = Boolean(selectedMapItem);
  const selectLandmark = (landmark: (typeof physicalMap.landmarks)[number]) => {
    const ride = mapFlow.rides.find((item) => item.id === landmark.id || item.name === landmark.name);
    const food = mapParkState?.foodInventory?.locations.find((item) => item.id === landmark.id || item.name === landmark.name);
    const isFood = landmark.type === "food" || Boolean(food);
    const status = ride?.status ?? (food ? `${food.pickupEtaMinutes}m pickup` : landmark.type.replaceAll("_", " "));
    const waitMins = ride?.waitMins ?? food?.pickupEtaMinutes;
    const guests = ride?.queueGuests ?? food?.mobileOrderBacklog;
    const tone = selectionTone(status, ride ? ride.waitMins + ride.queueGuests / 35 : food?.pickupEtaMinutes);
    focusMapSelection(landmark.name, landmark.x + landmark.w / 2, landmark.y + landmark.h / 2, landmark.w > 220 ? 1.2 : 1.45);
    selectMapItem({
      id: landmark.id,
      kind: "attraction",
      title: landmark.name,
      subtitle: isFood ? "Food and mobile order area" : ride ? "Attraction" : landmark.guestVisible ? "Guest area" : "Operations area",
      status,
      tone,
      waitMins,
      guests,
      detail: ride
        ? `${ride.queueGuests.toLocaleString()} guests waiting, ${ride.waitMins} minute wait, ${ride.status} status.`
        : food
          ? `${food.mobileOrderBacklog} mobile orders, ${food.pickupEtaMinutes} minute pickup estimate.`
          : landmark.guestVisible
            ? "Guest-visible location on the park map."
            : "Backstage area; use for operations routing only.",
      actions: isFood
        ? ["Reduce food line", "Message mobile orders", "Send kitchen support"]
        : ride
          ? ["Reduce queue", "Send staff", ride.status === "down" ? "Pause intake" : "Message guests"]
          : ["Inspect area", "Send staff", "Message nearby guests"],
      prompt: isFood
        ? `${landmark.name} needs attention. Reduce pickup pressure, message mobile-order guests, and send staff without overloading nearby paths.`
        : ride
          ? `${landmark.name} needs attention. Reduce the queue, message guests honestly, and send staff while respecting safety and coverage rules.`
          : `Check ${landmark.name}. Review guest flow and prepare a bounded staff or guest message if needed.`,
    });
  };
  const selectQueue = (queue: (typeof physicalMap.queues)[number]) => {
    const tone = selectionTone(queue.spillbackRisk, queue.waitMins + queue.guests / 25);
    const focusPoint = queue.points[Math.max(0, Math.floor(queue.points.length / 2) - 1)] ?? [500, 340];
    focusMapSelection(queue.name, focusPoint[0], focusPoint[1], 1.5);
    selectMapItem({
      id: queue.id,
      kind: "queue",
      title: queue.name,
      subtitle: "Queue footprint",
      status: queue.spillbackRisk,
      tone,
      waitMins: queue.waitMins,
      guests: queue.guests,
      detail: `${queue.guests.toLocaleString()} guests, ${queue.waitMins} minute wait, ${queue.shadePct}% shade coverage.`,
      actions: ["Reduce queue", "Pause intake", "Open alternate route"],
      prompt: `${queue.name} has ${queue.guests} guests and a ${queue.waitMins} minute wait. Reduce the queue, pause new intake if needed, and route guests to safe alternatives.`,
    });
  };
  const selectFacility = (facility: (typeof physicalMap.facilities)[number]) => {
    const tone = selectionTone(undefined, facility.waitMins * 8);
    focusMapSelection(facility.name, facility.x, facility.y, 1.55);
    selectMapItem({
      id: facility.id,
      kind: "facility",
      title: facility.name,
      subtitle: facility.type.replaceAll("_", " "),
      status: facility.waitMins >= 8 ? "busy" : "open",
      tone,
      waitMins: facility.waitMins,
      detail: `${facility.name} has a ${facility.waitMins} minute local wait.`,
      actions: ["Send staff", "Message nearby guests", "Inspect area"],
      prompt: `${facility.name} needs a quick check. Review local wait pressure, send staff if needed, and message nearby guests with clear options.`,
    });
  };
  const selectSupportStation = (station: (typeof physicalMap.supportStations)[number]) => {
    const tone = station.status === "offline" ? "risk" : selectionTone(station.status, station.waitMins * 10);
    focusMapSelection(station.name, station.x, station.y, 1.55);
    selectMapItem({
      id: station.id,
      kind: "support-station",
      title: station.name,
      subtitle: `${station.agentName} customer support agent`,
      status: station.status,
      tone,
      waitMins: station.waitMins,
      detail: `${station.agentName} answers ${station.specialties.join(", ")}. Current kiosk wait is ${station.waitMins} minutes.`,
      actions: [
        "Ask a question",
        "Get recommendation",
        ...station.sampleQuestions.slice(0, 2),
      ],
      prompt: `${station.name} customer support station is helping guests. Answer customer questions and recommend the best next stop using current waits, crowd density, accessibility, food pressure, and weather. Sample recommendation: ${station.recommendations[0] ?? "recommend a low-wait, low-crowd option nearby"}.`,
    });
  };
  const selectGuestGroup = (group: (typeof physicalMap.guestGroups)[number]) => {
    const tone = selectionTone(group.mood, group.count / 3);
    focusMapSelection(group.segment, group.x, group.y, 1.55);
    selectMapItem({
      id: group.id,
      kind: "guest-group",
      title: group.segment,
      subtitle: `Heading to ${group.destination}`,
      status: group.mood.replaceAll("_", " "),
      tone,
      guests: group.count,
      detail: `${group.count.toLocaleString()} guests moving ${group.pace}; current mood is ${group.mood.replaceAll("_", " ")}.`,
      actions: ["Message guests", "Open alternate route", "Send staff"],
      prompt: `${group.segment} need guidance toward ${group.destination}. Send a clear guest message and staff support without exposing individual guest data.`,
    });
  };

  if (compact) {
    const statusGood = !rides.some((ride) => ride.status === "down") && metricPreview.every((metric) => metric.tone !== "risk");
    const queueAlerts = physicalMap.queues.filter((queue) => queue.spillbackRisk !== "normal").length;
    const namedLandmark = (id: string) => physicalMap.landmarks.find((landmark) => landmark.id === id) ?? physicalMap.landmarks[0];
    const hotSpots = [
      {
        id: "indoorLaunch",
        x: 314,
        y: 152,
        r: 22,
        label: "Indoor Ride Hub",
        value: `${Math.max(48, Math.min(120, avgWait * 2))}% / ${avgWait + 8}m`,
        guests: `${Math.max(900, totalQueue).toLocaleString()} guests`,
        tone: avgWait > 35 ? "#dc2626" : "#059669",
        select: () => selectLandmark(namedLandmark("indoorLaunch")),
      },
      {
        id: "dragonCoaster",
        x: 832,
        y: 210,
        r: 24,
        label: "Coaster Plaza",
        value: `${Math.max(70, Math.round((mapFlow.rides.find((ride) => ride.id === "dragonCoaster")?.downtimeRisk ?? 58) + 42))}% / ${mapFlow.rides.find((ride) => ride.id === "dragonCoaster")?.waitMins ?? 63}m`,
        guests: `${(mapFlow.rides.find((ride) => ride.id === "dragonCoaster")?.queueGuests ?? 1933).toLocaleString()} guests`,
        tone: "#dc2626",
        select: () => selectLandmark(namedLandmark("dragonCoaster")),
      },
      {
        id: "arcade",
        x: 316,
        y: 344,
        r: 19,
        label: "Arcade Zone",
        value: `${Math.max(45, Math.min(72, busiestZone?.density ?? 52))}% / 7m`,
        guests: "1,144 guests",
        tone: "#059669",
        select: () => selectLandmark(namedLandmark("arcade")),
      },
      {
        id: "frontGate",
        x: 200,
        y: 442,
        r: 18,
        label: "Entrance Plaza",
        value: "54% / 3m",
        guests: "968 guests",
        tone: "#059669",
        select: () => selectLandmark(namedLandmark("frontGate")),
      },
      {
        id: "foodCourtA",
        x: 850,
        y: 430,
        r: 19,
        label: "Food Court 1",
        value: `${Math.max(58, Math.min(99, mapParkState?.foodInventory?.locations[0]?.pickupEtaMinutes ? mapParkState.foodInventory.locations[0].pickupEtaMinutes * 3 : 73))}% / ${mapParkState?.foodInventory?.locations[0]?.pickupEtaMinutes ?? 24}m`,
        guests: `${(mapParkState?.foodInventory?.locations[0]?.mobileOrderBacklog ?? 1026).toLocaleString()} guests`,
        tone: "#f59e0b",
        select: () => selectLandmark(namedLandmark("foodCourtA")),
      },
      {
        id: "firstAid",
        x: 545,
        y: 560,
        r: 16,
        label: "Care Lagoon",
        value: "65%",
        guests: "15 guests",
        tone: "#059669",
        select: () => selectLandmark(namedLandmark("firstAid")),
      },
      {
        id: "coveredPlaza",
        x: 690,
        y: 310,
        r: 18,
        label: "Covered Plaza",
        value: `${Math.max(62, showtimeRisk || 86)}% / 18m`,
        guests: "1,627 guests",
        tone: "#dc2626",
        select: () => selectLandmark(namedLandmark("paradeRoute")),
      },
    ];
    const selectedHotSpot = selectedMapItem ? hotSpots.find((spot) => spot.id === selectedMapItem.id) : undefined;
    const actionSummary = hasActionPayload
      ? showAfterState
        ? `Action applied: ${stateImpactLine}`
        : `Planning: ${customActionOverlay.headline}`
      : "Click a zone or run Scan/Proact to inspect live operations.";

    return (
      <section className="h-[calc(100vh-2.5rem)] min-h-[680px] bg-slate-950">
        <div className="relative h-full overflow-hidden bg-[#142519]">
          <svg
            className="absolute inset-0 h-full w-full transition-all duration-300"
            viewBox={viewBox}
            preserveAspectRatio="xMidYMid slice"
            role="img"
            aria-label="Reference style zoomable park operations map"
          >
            <defs>
              <filter id="reference-card-shadow" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="8" floodColor="#0f172a" floodOpacity="0.24" stdDeviation="7" />
              </filter>
            </defs>
            <image href="/park-reference-map.png" x="0" y="0" width="1000" height="650" preserveAspectRatio="xMidYMid slice" />
            <rect x="0" y="0" width="1000" height="650" fill="#07131b" opacity="0.08" />

            {(activeLayer === "signals" || showMapDetails) && (
              <g opacity={activeLayer === "signals" ? 0.95 : 0.82}>
                <path d="M182 518 C272 432 372 388 494 418 C602 444 690 412 788 363" stroke="#f59e0b" strokeWidth="7" strokeLinecap="round" strokeDasharray="18 13" fill="none" />
                <path d="M498 418 C548 360 604 338 690 310 C754 288 812 250 832 210" stroke="#ef4444" strokeWidth="7" strokeLinecap="round" strokeDasharray="18 13" fill="none" />
                <path d="M316 344 C402 398 472 440 545 560 C610 492 714 444 850 430" stroke="#10b981" strokeWidth="7" strokeLinecap="round" strokeDasharray="18 13" fill="none" />
                <path d="M314 152 C390 258 442 342 498 418 C524 468 536 520 545 560" stroke="#0ea5e9" strokeWidth="6" strokeLinecap="round" strokeDasharray="16 13" fill="none" />
              </g>
            )}

            {hotSpots.map((spot, index) => {
              const isSelected = selectedMapItem?.id === spot.id;
              const showMarker = isSelected || showMapLabels || activeLayer === "queues" || activeLayer === "signals";
              const showCard =
                isSelected ||
                showMapLabels ||
                (activeLayer === "queues" && ["dragonCoaster", "foodCourtA", "coveredPlaza"].includes(spot.id)) ||
                (activeLayer === "signals" && index < 3);
              const cardX = Math.min(852, Math.max(24, spot.x + (spot.x > 720 ? -8 : 34)));
              const cardY = Math.max(40, Math.min(566, spot.y - 38));
              return (
                <g
                  key={spot.id}
                  className="cursor-pointer outline-none"
                  opacity={hasMapSelection && !isSelected ? 0.48 : 1}
                  tabIndex={0}
                  role="button"
                  aria-label={`Select ${spot.label}`}
                  onClick={spot.select}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      spot.select();
                    }
                  }}
                >
                  {!showMarker && <circle cx={spot.x} cy={spot.y} r={spot.r + 24} fill="#000000" opacity="0" pointerEvents="all" />}
                  {showMarker && (
                    <>
                  <circle cx={spot.x} cy={spot.y} r={spot.r + 12} fill={spot.tone} opacity={isSelected ? "0.28" : "0.14"} />
                  <circle cx={spot.x} cy={spot.y} r={spot.r} fill={spot.tone} stroke="#fff7ed" strokeWidth="4" />
                  <text x={spot.x} y={spot.y + 5} textAnchor="middle" fill="#ffffff" fontSize="15" fontWeight="900">
                    {spot.value.match(/\d+/)?.[0] ?? "!"}
                  </text>
                    </>
                  )}
                  {showCard && (
                    <g filter="url(#reference-card-shadow)" transform={`translate(${cardX} ${cardY})`}>
                      <rect width="160" height="62" rx="8" fill="#fffaf0" stroke={spot.tone} strokeWidth={isSelected ? "4" : "2"} />
                      <circle cx="17" cy="16" r="7" fill={spot.tone} />
                      <text x="38" y="19" fill="#111827" fontSize="12" fontWeight="900">{spot.label}</text>
                      <text x="38" y="38" fill={spot.tone} fontSize="13" fontWeight="900">{spot.value}</text>
                      <text x="38" y="53" fill="#111827" fontSize="9" fontWeight="800">{spot.guests}</text>
                    </g>
                  )}
                </g>
              );
            })}

            {(activeLayer === "support" || showMapDetails) && physicalMap.supportStations.map((station) => {
              const isSelected = selectedKey === `support-station:${station.id}`;
              const tone = supportStationTone(station.status);
              return (
                <g
                  key={station.id}
                  className="cursor-pointer outline-none"
                  tabIndex={0}
                  role="button"
                  aria-label={`Select ${station.name}`}
                  onClick={() => selectSupportStation(station)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      selectSupportStation(station);
                    }
                  }}
                >
                  <circle cx={station.x} cy={station.y} r={isSelected ? "25" : "18"} fill="#f8fafc" stroke={tone} strokeWidth={isSelected ? "6" : "4"} />
                  <text x={station.x} y={station.y + 4} textAnchor="middle" fill={tone} fontSize="8" fontWeight="900">AI</text>
                </g>
              );
            })}

            {selectedHotSpot && (
              <g filter="url(#reference-card-shadow)" transform={`translate(${Math.max(26, selectedHotSpot.x - 100)} ${Math.max(58, selectedHotSpot.y + 48)})`}>
                <rect width="240" height="74" rx="10" fill="#ecfeff" stroke="#0891b2" strokeWidth="3" opacity="0.98" />
                <text x="13" y="20" fill="#164e63" fontSize="10" fontWeight="900">Selected zone</text>
                <text x="13" y="39" fill="#0f172a" fontSize="14" fontWeight="900">{selectedMapItem?.title ?? selectedHotSpot.label}</text>
                <text x="13" y="57" fill="#334155" fontSize="10" fontWeight="800">{selectedMapItem?.detail.slice(0, 42) ?? "Live operating detail"}</text>
              </g>
            )}

            <AgentMapGroundingOverlay grounding={agentMapGrounding} impactReplay={agentImpactReplay} replayPhase={agentReplayPhase} physicalMap={physicalMap} flow={mapFlow} />
          </svg>

          <div className="pointer-events-auto absolute left-3 top-3 z-40 min-h-[18.5rem] w-[min(17rem,calc(100%-1.5rem))] rounded-xl border border-white/15 bg-slate-950/90 p-3 text-slate-100 shadow-2xl backdrop-blur">
            <div className="flex items-center gap-2 text-sm font-black uppercase tracking-wide">
              <span className={`h-3 w-3 rounded-full ${isConnected ? "bg-emerald-400" : "bg-amber-300"}`} />
              Live
            </div>
            <div className="mt-2 rounded-lg bg-cyan-400/10 p-2.5">
              <div className="text-[10px] font-bold text-cyan-200">Park Clock</div>
              <div className="mt-1 text-lg font-black text-cyan-50">{parkClock}</div>
            </div>
            <div className="mt-3 rounded-lg bg-white/5 p-3">
              <div className="text-[10px] font-bold text-slate-400">Park Status</div>
              <div className={`mt-1 text-lg font-black ${statusGood ? "text-emerald-300" : "text-amber-300"}`}>{statusGood ? "Good" : "Watch"}</div>
            </div>
            <div className="mt-2 grid gap-2">
              <div className="rounded-lg bg-white/5 p-2.5">
                <div className="text-[10px] font-bold text-slate-400">Current Operations</div>
                <div className="mt-1 text-xs font-black text-emerald-100">{statusGood ? "All Systems Normal" : "Active mitigation"}</div>
              </div>
              <div className="rounded-lg bg-white/5 p-2.5">
                <div className="text-[10px] font-bold text-slate-400">Queue Alerts</div>
                <div className="mt-1 text-sm font-black text-slate-50">{queueAlerts}</div>
              </div>
            </div>
          </div>

          {hasActionPayload && (
            <div className="pointer-events-none absolute left-1/2 top-4 z-40 w-[min(28rem,calc(100%-34rem))] -translate-x-1/2 rounded-lg border border-white/30 bg-white/92 p-3 text-slate-950 shadow-2xl backdrop-blur max-xl:hidden">
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-700">{showAfterState ? "Map updated" : "Agent planning"}</div>
              <div className="mt-1 line-clamp-2 text-sm font-black">{actionSummary}</div>
            </div>
          )}

          {agentImpactReplay && (
            <ReplayPhaseControls
              phase={agentReplayPhase}
              hasAfterState={Boolean(agentImpactReplay.state?.guestFlow)}
              className="right-4 top-4 w-[min(31rem,calc(100%-19rem))] max-xl:left-1/2 max-xl:right-auto max-xl:top-24 max-xl:w-[min(31rem,calc(100%-1.5rem))] max-xl:-translate-x-1/2"
              onPhaseChange={updateAgentReplayPhase}
            />
          )}

          <div className="pointer-events-auto absolute bottom-4 left-4 z-40 flex overflow-hidden rounded-xl border border-white/12 bg-slate-950/88 p-1 text-slate-100 shadow-2xl backdrop-blur">
            {([
              ["attractions", "Overview"],
              ["queues", "Queues"],
              ["guests", "Capacity"],
              ["signals", "Incidents"],
              ["support", "Support"],
            ] as Array<[MapLayer, string]>).map(([layer, label]) => (
              <button
                key={layer}
                type="button"
                onClick={() => updateActiveLayer(layer)}
                className={`min-w-24 rounded-lg px-3 py-2 text-center text-[11px] font-black transition ${
                  activeLayer === layer ? "bg-slate-900 text-cyan-300 ring-1 ring-cyan-400/40" : "text-slate-300 hover:bg-white/8"
                }`}
              >
                <span className="block text-lg leading-none">{layer === "attractions" ? "MAP" : layer === "queues" ? "Q" : layer === "guests" ? "CAP" : layer === "signals" ? "!" : "AI"}</span>
                <span className="mt-1 block">{label}</span>
              </button>
            ))}
          </div>

          <div className="pointer-events-auto absolute bottom-4 right-4 z-40 flex items-center overflow-hidden rounded-xl border border-white/12 bg-slate-950/88 text-slate-100 shadow-2xl backdrop-blur">
            <button
              type="button"
              aria-label="Zoom out"
              onClick={() => setZoom((value) => Math.max(1, Number((value - 0.25).toFixed(2))))}
              className="h-14 w-14 text-2xl font-light hover:bg-white/10"
            >
              -
            </button>
            <button
              type="button"
              onClick={() => {
                setFocus(MAP_FOCUS_POINTS[0]);
                setZoom(1);
              }}
              className="h-14 min-w-20 border-x border-white/10 px-4 text-sm font-black hover:bg-white/10"
            >
              {Math.round(zoom * 100)}%
            </button>
            <button
              type="button"
              aria-label="Zoom in"
              onClick={() => setZoom((value) => Math.min(2.5, Number((value + 0.25).toFixed(2))))}
              className="h-14 w-14 text-2xl font-light hover:bg-white/10"
            >
              +
            </button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="grid min-h-[620px] gap-4 xl:grid-cols-[minmax(0,1.35fr)_26rem]">
      <div className={compact ? "relative h-[calc(100vh-2.5rem)] min-h-[680px] overflow-hidden bg-[#8fbc72]" : "relative min-h-[560px] overflow-hidden rounded-lg border border-slate-800 bg-[#8fbc72] shadow-2xl shadow-slate-950/35"}>
        <div className="absolute inset-0 bg-[linear-gradient(115deg,rgba(68,103,48,0.34),transparent_34%),radial-gradient(circle_at_25%_18%,rgba(212,231,184,0.55),transparent_18%),radial-gradient(circle_at_75%_76%,rgba(65,122,85,0.34),transparent_26%)]" />
        <div className="park-grass-texture absolute inset-0 opacity-70" />

        {!compact && <div className="absolute left-5 top-5 z-20 flex max-w-[calc(100%-2.5rem)] flex-wrap items-center gap-2">
          <span className={`rounded px-3 py-2 text-xs font-black shadow-lg ${isConnected ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-900"}`}>
            {isConnected ? "Live park feed" : "Local simulation"}
          </span>
          <span className="rounded bg-slate-950/90 px-3 py-2 text-xs font-black text-cyan-100 shadow-lg">Park {parkClock}</span>
          <span className="rounded bg-white/90 px-3 py-2 text-xs font-black text-stone-800 shadow-lg">{mapFlow.representedGuests.toLocaleString()} guests</span>
          <span className="rounded bg-white/90 px-3 py-2 text-xs font-black text-stone-800 shadow-lg">{avgWait}m avg wait</span>
          <span className="rounded bg-white/90 px-3 py-2 text-xs font-black text-stone-800 shadow-lg">{scaleLabel}</span>
          {operatingClock && (
            <span className="rounded bg-cyan-100 px-3 py-2 text-xs font-black text-cyan-950 shadow-lg">
              {operatingClock.phase.label} · {pct(operatingClock.phase.demandPressurePct)}
            </span>
          )}
          {nextShowtime && (
            <span className="rounded bg-violet-100 px-3 py-2 text-xs font-black text-violet-950 shadow-lg">
              {nextShowtime.name} · {pct(showtimeRisk)}
            </span>
          )}
          {accessFairness && (
            <span className="rounded bg-red-100 px-3 py-2 text-xs font-black text-red-950 shadow-lg">
              Fast Lane fairness · {pct(accessFairness.publicComplaintRiskPct)}
            </span>
          )}
          <span className="flex overflow-hidden rounded bg-white/90 shadow-lg">
            {(["past", "now", "future"] as MapTimeLens[]).map((lens) => (
              <button
                key={lens}
                type="button"
                onClick={() => setTimeLens(lens)}
                className={`px-3 py-2 text-xs font-black uppercase ${timeLens === lens ? "bg-slate-950 text-white" : "text-stone-700 hover:bg-stone-100"}`}
              >
                {lens === "future" ? "+15m" : lens}
              </button>
            ))}
          </span>
        </div>}

        {compact && showOverlayControls && <div className="absolute left-3 top-3 z-40 flex max-w-[calc(100%-1.5rem)] flex-wrap gap-1 rounded-lg border border-white/45 bg-slate-950/78 p-1.5 text-white shadow-xl shadow-stone-950/25 backdrop-blur">
          {(["attractions", "queues", "support", "signals"] as MapLayer[]).map((layer) => (
            <button
              key={layer}
              type="button"
              onClick={() => updateActiveLayer(layer)}
              className={`rounded px-2.5 py-1.5 text-[9px] font-black uppercase tracking-widest transition ${activeLayer === layer ? "bg-cyan-300 text-slate-950" : "bg-white/10 text-slate-200 hover:bg-white/18"}`}
            >
              {MAP_LAYERS.find((item) => item.id === layer)?.label ?? layer}
            </button>
          ))}
          <button
            type="button"
            onClick={() => updateShowMapLabels(!showMapLabels)}
            className={`rounded px-2.5 py-1.5 text-[9px] font-black uppercase tracking-widest transition ${showMapLabels ? "bg-emerald-300 text-slate-950" : "bg-white/10 text-slate-200 hover:bg-white/18"}`}
          >
            Labels
          </button>
          <button
            type="button"
            onClick={() => updateShowMapDetails(!showMapDetails)}
            className={`rounded px-2.5 py-1.5 text-[9px] font-black uppercase tracking-widest transition ${showMapDetails ? "bg-amber-300 text-slate-950" : "bg-white/10 text-slate-200 hover:bg-white/18"}`}
          >
            Details
          </button>
          {operatingClock && (
            <span className="rounded bg-cyan-300 px-2.5 py-1.5 text-[9px] font-black uppercase tracking-widest text-slate-950">
              {operatingClock.phase.eventWave.replaceAll("_", " ")}
            </span>
          )}
          {nextShowtime && (
            <span className="rounded bg-violet-300 px-2.5 py-1.5 text-[9px] font-black uppercase tracking-widest text-slate-950">
              {nextShowtime.name.slice(0, 12)}
            </span>
          )}
          {accessFairness && (
            <span className="rounded bg-red-300 px-2.5 py-1.5 text-[9px] font-black uppercase tracking-widest text-slate-950">
              VIP {pct(accessFairness.premiumLaneSharePct)}
            </span>
          )}
          <span className="flex overflow-hidden rounded">
            {(["past", "now", "future"] as MapTimeLens[]).map((lens) => (
              <button
                key={lens}
                type="button"
                onClick={() => setTimeLens(lens)}
                className={`px-2.5 py-1.5 text-[9px] font-black uppercase tracking-widest transition ${timeLens === lens ? "bg-violet-300 text-slate-950" : "bg-white/10 text-slate-200 hover:bg-white/18"}`}
              >
                {lens === "future" ? "+15m" : lens}
              </button>
            ))}
          </span>
        </div>}

        {agentImpactReplay && (
          <ReplayPhaseControls
            phase={agentReplayPhase}
            hasAfterState={Boolean(agentImpactReplay.state?.guestFlow)}
            onPhaseChange={updateAgentReplayPhase}
          />
        )}

        {!compact && <div className="absolute left-5 top-20 z-40 max-w-[calc(100%-2.5rem)] rounded-lg border border-white/70 bg-white/92 p-2 shadow-xl shadow-stone-950/20 backdrop-blur">
          <div className="flex flex-wrap gap-1">
            {MAP_LAYERS.map((layer) => (
              <button
                key={layer.id}
                type="button"
                onClick={() => updateActiveLayer(layer.id)}
                className={`rounded px-3 py-2 text-[10px] font-black uppercase tracking-widest transition ${activeLayer === layer.id ? "bg-stone-900 text-white" : "bg-stone-100 text-stone-700 hover:bg-stone-200"}`}
                title={layer.detail}
              >
                {layer.label}
              </button>
            ))}
          </div>
        </div>}

        {!compact && <div className="absolute bottom-32 right-5 z-40 grid w-48 gap-2 rounded-lg border border-white/70 bg-white/92 p-3 text-stone-800 shadow-xl shadow-stone-950/20 backdrop-blur">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-stone-500">Zoom</div>
              <div className="text-xs font-black text-stone-900">{focus.label} / {zoom.toFixed(1)}x</div>
            </div>
            <div className="flex gap-1">
              <button type="button" onClick={() => setZoom((value) => Math.max(1, Number((value - 0.25).toFixed(2))))} className="h-8 w-8 rounded bg-stone-900 text-sm font-black text-white">-</button>
              <button type="button" onClick={() => setZoom((value) => Math.min(2.5, Number((value + 0.25).toFixed(2))))} className="h-8 w-8 rounded bg-stone-900 text-sm font-black text-white">+</button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-1">
            {MAP_FOCUS_POINTS.map((point) => (
              <button
                key={point.label}
                type="button"
                onClick={() => {
                  setFocus(point);
                  setZoom(point.zoom);
                }}
                className="rounded bg-stone-100 px-2 py-1.5 text-[10px] font-black text-stone-700 hover:bg-stone-200"
              >
                {point.label}
              </button>
            ))}
          </div>
        </div>}

        <svg className={compact ? "absolute inset-0 z-10 h-full w-full transition-all duration-300" : "absolute inset-0 z-10 h-full w-full transition-all duration-300"} viewBox={viewBox} role="img" aria-label="Layered zoomable theme park operations map">
          <defs>
            <filter id="map-shadow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="7" floodColor="#2b2419" floodOpacity="0.22" stdDeviation="7" />
            </filter>
            <linearGradient id="pond-water" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0%" stopColor="#9bd4e9" />
              <stop offset="100%" stopColor="#357f99" />
            </linearGradient>
            <pattern id="roof-stripes" width="16" height="16" patternUnits="userSpaceOnUse">
              <path d="M0 16 L16 0" stroke="#ffffff" strokeOpacity="0.28" strokeWidth="4" />
            </pattern>
          </defs>

          <path d="M-25 544 C125 505 195 526 305 574 C412 621 535 622 686 584 C801 555 908 564 1034 606 L1034 685 L-25 685 Z" fill="#d8c08b" opacity="0.55" />
          <path d="M-40 585 C98 548 183 530 283 560 C407 598 526 628 692 594 C782 576 877 580 1040 622 L1040 690 L-40 690 Z" fill="#706f5e" opacity="0.34" />
          <path d="M34 598 L336 598 L336 650 L34 650 Z" fill="#4b5563" opacity="0.42" />
          <path d="M46 610 L324 610 M46 626 L324 626 M46 642 L324 642" stroke="#d1d5db" strokeWidth="2" strokeDasharray="18 14" opacity="0.75" />
          <path d="M672 397 C733 356 808 365 852 413 C893 459 854 528 777 535 C691 544 626 494 640 444 C645 424 654 409 672 397 Z" fill="url(#pond-water)" opacity="0.92" />
          <path d="M681 415 C733 385 798 390 830 428 C860 462 826 507 772 514 C712 522 659 490 662 452 C664 437 670 424 681 415 Z" fill="#bde9f3" opacity="0.42" />

          {showOperations && physicalMap.serviceRoutes.map((route) => (
            <g key={route.id}>
              <path
                d={pointsToPath(route.points)}
                stroke={route.blocked ? "#ef4444" : route.access === "emergency" ? "#2563eb" : "#475569"}
                strokeDasharray={route.access === "emergency" ? "14 10" : "9 12"}
                strokeLinecap="round"
                strokeWidth={route.access === "emergency" ? 8 : 6}
                fill="none"
                opacity={route.blocked ? 0.82 : 0.56}
              />
              {route.blocked && <path className="park-flow-line" d={pointsToPath(route.points)} stroke="#fbbf24" strokeLinecap="round" strokeWidth="2" fill="none" />}
            </g>
          ))}

          {([
            ["M188 522 C292 438 404 372 528 315 C650 259 740 209 876 150", 34],
            ["M157 200 C281 227 381 269 493 340 C594 404 706 450 831 478", 30],
            ["M330 110 C346 226 369 348 414 532", 25],
            ["M120 484 C238 438 349 432 483 458 C562 473 642 483 748 484", 25],
          ] as const).map(([d, width]) => (
            <g key={d}>
              <path d={d} stroke="#b8915b" strokeLinecap="round" strokeWidth={Number(width) + 10} fill="none" opacity="0.26" />
              <path d={d} stroke="#ead5a5" strokeLinecap="round" strokeWidth={width} fill="none" />
              <path d={d} stroke="#fff6d8" strokeDasharray="3 18" strokeLinecap="round" strokeWidth="3" fill="none" opacity="0.8" />
            </g>
          ))}

          {showOperatingClockOverlay && operatingClock && (
            <OperatingClockMapOverlay clock={operatingClock} showLabels={showOperatingClockLabels} />
          )}

          {operatingClock && (!compact || activeLayer === "signals" || showMapDetails) && <ShowtimeMapOverlay clock={operatingClock} />}
          {operatingClock && (!compact || activeLayer === "signals" || showMapDetails) && <FastLaneFairnessMapOverlay clock={operatingClock} />}

          <TimeLapseMapOverlay lens={timeLens} physicalMap={physicalMap} flow={mapFlow} clock={operatingClock} />

          <g filter="url(#map-shadow)">
            <path d="M625 104 C697 60 798 75 866 136 C910 177 912 244 865 279 C805 323 712 301 650 248 C599 204 578 137 625 104 Z" fill="#654533" opacity="0.92" />
            <path d="M650 128 C707 92 782 105 838 153 C874 184 876 232 838 256 C790 286 719 269 670 228 C628 193 612 153 650 128 Z" fill="#9d6d44" />
            <path d="M637 175 C690 115 793 111 849 170 C882 205 851 257 792 265 C719 276 651 238 637 175 Z" fill="none" stroke="#2f2926" strokeWidth="9" />
            <path d="M637 175 C690 115 793 111 849 170 C882 205 851 257 792 265 C719 276 651 238 637 175 Z" fill="none" stroke="#dc2626" strokeDasharray="22 16" strokeWidth="5" />
            {[
              [686, 144],
              [746, 122],
              [813, 164],
              [823, 225],
              [758, 253],
              [684, 218],
            ].map(([x, y]) => (
              <line key={`${x}-${y}`} x1={x} x2={x - 12} y1={y} y2={y + 44} stroke="#55413a" strokeWidth="4" />
            ))}
          </g>

          {showAttractions && physicalMap.landmarks.map((landmark) => {
            const label = landmarkTextAnchor(landmark);
            const isSelected = selectedKey === `attraction:${landmark.id}`;
            return (
            <g
              key={landmark.id}
              className="cursor-pointer outline-none"
              filter="url(#map-shadow)"
              opacity={hasMapSelection && !isSelected ? 0.42 : landmark.guestVisible ? 1 : 0.82}
              tabIndex={0}
              role="button"
              aria-label={`Select ${landmark.name}`}
              onClick={() => selectLandmark(landmark)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  selectLandmark(landmark);
                }
              }}
            >
              <title>{landmark.name}</title>
              <rect
                x={landmark.x}
                y={landmark.y}
                width={landmark.w}
                height={landmark.h}
                rx={landmark.type === "backstage" ? 7 : 14}
                fill={landmarkFill(landmark.type)}
                stroke={isSelected ? selectionStroke(selectedMapItem?.tone ?? "ok") : landmark.type === "backstage" ? "#334155" : "#fff7ed"}
                strokeWidth={isSelected ? "7" : "3"}
                opacity={landmark.type === "water" ? 0.25 : 0.92}
              />
              {isSelected && (
                <rect
                  x={landmark.x - 8}
                  y={landmark.y - 8}
                  width={landmark.w + 16}
                  height={landmark.h + 16}
                  rx={landmark.type === "backstage" ? 10 : 18}
                  fill="none"
                  stroke={selectionStroke(selectedMapItem?.tone ?? "ok")}
                  strokeDasharray="12 8"
                  strokeWidth="4"
                  opacity="0.9"
                />
              )}
              {landmark.type !== "water" && (!compact || isSelected || (showMapLabels && compactLandmarkIds.has(landmark.id))) && (
                <text x={label.x} y={label.y} fill={landmark.type === "backstage" ? "#f8fafc" : "#332c22"} fontSize={activeLayer === "attractions" ? "16" : "13"} fontWeight="900">
                  {landmark.name}
                </text>
              )}
              {!landmark.guestVisible && (!compact || showMapDetails || isSelected) && (
                <text x={landmark.x + 10} y={landmark.y + landmark.h - 12} fill="#fca5a5" fontSize="10" fontWeight="900">
                  BACKSTAGE
                </text>
              )}
            </g>
          );
          })}

          {showQueues && physicalMap.queues.map((queue) => {
            const tone = queue.spillbackRisk === "critical" ? "#dc2626" : queue.spillbackRisk === "watch" ? "#d97706" : "#059669";
            const path = pointsToPath(queue.points);
            const labelPoint = queue.points[Math.max(0, Math.floor(queue.points.length / 2) - 1)] ?? [0, 0];
            const isSelected = selectedKey === `queue:${queue.id}`;
            const shouldLabelQueue =
              isSelected ||
              (!compact) ||
              (showMapDetails &&
                ((hasCustomContext && queue.spillbackRisk === "critical") ||
                  (scenario.key === "food_spike" && queue.id === "foodPickupQueue") ||
                  (scenario.key === "storm_response" && queue.id === "indoorLaunchQueue")));
            return (
              <g
                key={queue.id}
                className="cursor-pointer outline-none"
                opacity={hasMapSelection && !isSelected ? 0.38 : 1}
                tabIndex={0}
                role="button"
                aria-label={`Select ${queue.name}`}
                onClick={() => selectQueue(queue)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectQueue(queue);
                  }
                }}
              >
                <title>{`${queue.name}: ${queue.waitMins} minute wait, ${queue.guests} guests`}</title>
                <path d={path} stroke={isSelected ? selectionStroke(selectedMapItem?.tone ?? "watch") : "#2b2118"} strokeLinecap="round" strokeLinejoin="round" strokeWidth={isSelected ? "28" : "20"} fill="none" opacity={isSelected ? "0.34" : "0.18"} />
                <path d={path} stroke={isSelected ? selectionStroke(selectedMapItem?.tone ?? "watch") : tone} strokeLinecap="round" strokeLinejoin="round" strokeWidth={isSelected ? "14" : "10"} fill="none" opacity="0.82" />
                <path className={queue.status === "down" || queue.spillbackRisk === "critical" ? "park-flow-line" : ""} d={path} stroke="#fff7ed" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" fill="none" opacity="0.88" />
                {shouldLabelQueue && <g transform={`translate(${labelPoint[0] + 8} ${labelPoint[1] - 28})`}>
                  <rect width="110" height="34" rx="8" fill="#fff7ed" stroke={tone} strokeWidth="2" opacity="0.96" />
                  <text x="9" y="14" fill="#292524" fontSize="10" fontWeight="900">{queue.waitMins}m / {queue.guests}</text>
                  <text x="9" y="27" fill="#57534e" fontSize="9" fontWeight="800">{queue.shadePct}% shade</text>
                </g>}
              </g>
            );
          })}

          <g filter="url(#map-shadow)">
            <path d="M126 92 L342 62 L415 145 L387 254 L171 273 L91 190 Z" fill="#dee7df" />
            <path d="M126 92 L342 62 L415 145 L387 254 L171 273 L91 190 Z" fill="url(#roof-stripes)" opacity="0.8" />
            <path d="M178 305 L401 300 L427 397 L210 420 Z" fill="#394c54" />
            <path d="M200 326 L379 322 L398 381 L222 398 Z" fill="#617b82" />
            <path d="M466 262 L637 246 L691 323 L655 394 L486 407 L430 332 Z" fill="#d5b36e" />
            <path d="M487 285 L623 274 L661 329 L633 372 L499 383 L461 333 Z" fill="#f7df9e" />
            <rect x="576" y="462" width="235" height="89" rx="16" fill="#f2ead7" />
            <rect x="598" y="480" width="66" height="52" rx="9" fill="#e85242" />
            <rect x="680" y="480" width="107" height="52" rx="9" fill="#72b8d5" />
            <path d="M119 418 C155 379 230 377 269 414 C297 442 290 486 249 505 C196 529 128 501 110 459 C104 445 106 430 119 418 Z" fill="#596b7a" />
            <path d="M141 432 C171 405 226 403 252 428 C271 447 264 476 234 489 C196 505 145 486 132 457 C128 448 130 439 141 432 Z" fill="#91a6b2" />
          </g>

          {([
            [69, 119],
            [76, 295],
            [118, 364],
            [183, 52],
            [230, 565],
            [275, 92],
            [311, 502],
            [426, 73],
            [459, 520],
            [521, 176],
            [529, 561],
            [584, 103],
            [600, 425],
            [717, 69],
            [875, 337],
            [916, 463],
            [927, 206],
            [950, 573],
          ] as const).map(([x, y]) => (
            <g key={`${x}-${y}`}>
              <circle cx={x} cy={y} r="18" fill="#246b42" />
              <circle cx={x - 7} cy={y + 5} r="12" fill="#3f8f4d" />
              <rect x={x - 3} y={y + 13} width="6" height="18" rx="2" fill="#6b4a2d" />
            </g>
          ))}

          {showSignals && ([
            ["M210 170 C365 150 490 190 710 175", "#dc2626", "7"],
            ["M720 250 C650 330 555 388 430 430", "#d97706", "6"],
            ["M265 450 C410 385 535 410 690 475", "#16a34a", "5"],
            ["M385 130 C382 250 405 365 500 545", "#0284c7", "4"],
          ] as const).map(([d, color, width]) => (
            <g key={d}>
              <path d={d} stroke={color} strokeWidth={width} strokeLinecap="round" fill="none" opacity="0.28" />
              <path className="park-flow-line" d={d} stroke={color} strokeWidth="2" strokeLinecap="round" fill="none" opacity="0.85" />
            </g>
          ))}

          {showGuests && physicalMap.guestGroups.map((group) => {
            const radius = Math.max(11, Math.min(32, Math.sqrt(group.count) * 1.45));
            const isSelected = selectedKey === `guest-group:${group.id}`;
            return (
              <g
                key={group.id}
                className="cursor-pointer outline-none"
                opacity={hasMapSelection && !isSelected ? 0.42 : 1}
                tabIndex={0}
                role="button"
                aria-label={`Select ${group.segment}`}
                onClick={() => selectGuestGroup(group)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectGuestGroup(group);
                  }
                }}
              >
                <title>{`${group.segment}: ${group.count} guests`}</title>
                <circle cx={group.x} cy={group.y} r={isSelected ? radius + 16 : radius + 7} fill={isSelected ? selectionStroke(selectedMapItem?.tone ?? "watch") : groupTone(group.mood)} opacity={isSelected ? "0.22" : "0.12"} />
                <circle cx={group.x} cy={group.y} r={radius} fill={groupTone(group.mood)} stroke={isSelected ? selectionStroke(selectedMapItem?.tone ?? "watch") : "transparent"} strokeWidth={isSelected ? "5" : "0"} opacity="0.72" />
                <circle cx={group.x - radius / 3} cy={group.y - radius / 4} r={Math.max(3, radius / 5)} fill="#fff7ed" opacity="0.78" />
                {(!compact || showMapDetails || isSelected) && (
                  <>
                    <text x={group.x + radius + 6} y={group.y - 2} fill="#1c1917" fontSize="11" fontWeight="900">{group.count}</text>
                    <text x={group.x + radius + 6} y={group.y + 12} fill="#57534e" fontSize="9" fontWeight="800">{group.destination}</text>
                  </>
                )}
              </g>
            );
          })}

          {([
            [706, 192],
            [728, 205],
            [749, 217],
            [770, 230],
            [318, 202],
            [343, 216],
            [369, 234],
            [600, 497],
            [624, 503],
            [648, 508],
            [229, 445],
            [250, 458],
            [273, 467],
          ] as const).map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r="5" fill="#1f2937" opacity="0.75" />
          ))}

          {showSupport && physicalMap.supportStations.map((station) => {
            const tone = supportStationTone(station.status);
            const isSelected = selectedKey === `support-station:${station.id}`;
            const labelX = station.x + 24;
            const labelY = station.y - 34;
            const showLabel = isSelected || (!compact && (activeLayer === "support" || activeLayer === "overview")) || (compact && showMapLabels && station.status !== "online");
            return (
              <g
                key={station.id}
                className="cursor-pointer outline-none"
                opacity={hasMapSelection && !isSelected ? 0.42 : 1}
                tabIndex={0}
                role="button"
                aria-label={`Select ${station.name} customer support station`}
                onClick={() => selectSupportStation(station)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectSupportStation(station);
                  }
                }}
              >
                <title>{`${station.name}: ${station.agentName} can answer questions and recommend routes`}</title>
                <circle className={station.status === "online" ? "park-node-pulse-svg" : ""} cx={station.x} cy={station.y} r={isSelected ? "34" : "26"} fill={tone} opacity={isSelected ? "0.24" : "0.16"} />
                <rect x={station.x - 19} y={station.y - 19} width="38" height="38" rx="10" fill="#f8fafc" stroke={isSelected ? selectionStroke(selectedMapItem?.tone ?? "ok") : tone} strokeWidth={isSelected ? "6" : "4"} />
                <path d={`M${station.x - 9} ${station.y - 6} H${station.x + 9} Q${station.x + 15} ${station.y - 6} ${station.x + 15} ${station.y} V${station.y + 4} Q${station.x + 15} ${station.y + 10} ${station.x + 9} ${station.y + 10} H${station.x + 2} L${station.x - 7} ${station.y + 17} L${station.x - 4} ${station.y + 10} H${station.x - 9} Q${station.x - 15} ${station.y + 10} ${station.x - 15} ${station.y + 4} V${station.y} Q${station.x - 15} ${station.y - 6} ${station.x - 9} ${station.y - 6} Z`} fill={tone} opacity="0.9" />
                <text x={station.x} y={station.y + 4} textAnchor="middle" fill="#f8fafc" fontSize="8" fontWeight="900">AI</text>
                <circle cx={station.x + 16} cy={station.y - 16} r="8" fill={station.status === "busy" ? "#fbbf24" : station.status === "offline" ? "#94a3b8" : "#22d3ee"} stroke="#f8fafc" strokeWidth="2" />
                {showLabel && (
                  <g transform={`translate(${labelX} ${labelY})`}>
                    <rect width="154" height="52" rx="9" fill="#f8fafc" stroke={tone} strokeWidth="2" opacity="0.95" />
                    <text x="9" y="16" fill="#0f172a" fontSize="10" fontWeight="900">{station.name.slice(0, 21)}</text>
                    <text x="9" y="31" fill={tone} fontSize="9" fontWeight="900">{station.agentName} / {station.waitMins}m wait</text>
                    <text x="9" y="44" fill="#475569" fontSize="8.5" fontWeight="800">Questions + recommendations</text>
                  </g>
                )}
              </g>
            );
          })}

          {showAiResponse && (
            <DomainPhysicalEffects
              domain={visualDomain}
              showAfterState={showAfterState}
              beforeAfterLine={beforeAfterLine}
              dispatchTotal={dispatchTotal || 0}
              aiFocus={aiFocus}
              customActionOverlay={customActionOverlay}
            />
          )}

          {showOperations && physicalMap.facilities.map((facility) => (
            <g
              key={facility.id}
              className="cursor-pointer outline-none"
              opacity={hasMapSelection && selectedKey !== `facility:${facility.id}` ? 0.42 : 1}
              tabIndex={0}
              role="button"
              aria-label={`Select ${facility.name}`}
              onClick={() => selectFacility(facility)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  selectFacility(facility);
                }
              }}
            >
              <title>{`${facility.name}: ${facility.waitMins} minute wait`}</title>
              <circle cx={facility.x} cy={facility.y} r={selectedKey === `facility:${facility.id}` ? "22" : "16"} fill="#f8fafc" stroke={selectedKey === `facility:${facility.id}` ? selectionStroke(selectedMapItem?.tone ?? "ok") : facility.waitMins >= 8 ? "#f59e0b" : "#0f766e"} strokeWidth={selectedKey === `facility:${facility.id}` ? "5" : "3"} />
              <text x={facility.x} y={facility.y + 4} textAnchor="middle" fill="#1f2937" fontSize="9" fontWeight="900">{facilityGlyph(facility.type)}</text>
              {facility.waitMins > 0 && (!compact || showMapDetails || selectedKey === `facility:${facility.id}`) && <text x={facility.x + 20} y={facility.y + 4} fill="#292524" fontSize="10" fontWeight="900">{facility.waitMins}m</text>}
            </g>
          ))}

          {showSignals && mapFlow.zones.map((zone) => {
            const layout = ZONE_LAYOUT[zone.id] ?? { x: 40, y: 40, w: 20, h: 20, kind: "indoor" as const };
            const cx = (layout.x + layout.w / 2) * 10;
            const cy = (layout.y + layout.h / 2) * 6.5;
            const tone = pressureTone(zone.density);
            const color = tone === "risk" ? "#dc2626" : tone === "watch" ? "#d97706" : "#059669";
            return (
              <g key={zone.id}>
                <circle cx={cx} cy={cy} r={tone === "risk" ? 28 : 22} fill={color} opacity="0.14" />
                <circle cx={cx} cy={cy} r="10" fill={color} stroke="#fff7ed" strokeWidth="3" />
                <g transform={`translate(${cx + 16} ${cy - 25})`}>
                  <rect width="132" height="50" rx="8" fill="#fff7ed" stroke={color} strokeWidth="2" opacity="0.96" />
                  <text x="9" y="16" fill="#292524" fontSize="10" fontWeight="900">{zone.name}</text>
                  <text x="9" y="31" fill={color} fontSize="10" fontWeight="900">{pct(zone.density)} / {zone.waitMins}m</text>
                  <text x="9" y="43" fill="#57534e" fontSize="8" fontWeight="800">{zone.currentGuests.toLocaleString()} guests</text>
                </g>
              </g>
            );
          })}

          {showSignals && rides.slice(0, 4).map((ride) => {
            const landmark = physicalMap.landmarks.find((item) => item.id === ride.id || item.name === ride.name);
            if (!landmark) return null;
            const cx = landmark.x + landmark.w / 2;
            const cy = landmark.y + landmark.h / 2;
            return (
              <g key={ride.id}>
                <circle className={ride.status !== "normal" ? "park-node-pulse-svg" : ""} cx={cx} cy={cy} r="22" fill={ride.status === "down" ? "#ef4444" : ride.status === "constrained" ? "#f59e0b" : "#10b981"} stroke="#fff7ed" strokeWidth="5" />
                <text x={cx} y={cy + 5} textAnchor="middle" fill="#1c1917" fontSize="13" fontWeight="900">{ride.waitMins}</text>
              </g>
            );
          })}

          <AgentMapGroundingOverlay grounding={agentMapGrounding} impactReplay={agentImpactReplay} replayPhase={agentReplayPhase} physicalMap={physicalMap} flow={mapFlow} />

          {showDetailedActionAnnotations && (
            <g>
              <g transform={`translate(${Math.max(24, aiFocus.detect.x - 118)} ${Math.max(76, aiFocus.detect.y - 92)})`}>
                <rect width="160" height="46" rx="10" fill="#fff1f2" stroke="#ef4444" strokeWidth="3" />
                <text x="11" y="17" fill="#991b1b" fontSize="10" fontWeight="900">Before</text>
                <text x="11" y="33" fill="#7f1d1d" fontSize="10" fontWeight="800">{proof.before}</text>
              </g>
              <circle className="park-node-pulse-svg" cx={aiFocus.detect.x} cy={aiFocus.detect.y} r="47" fill="#ef4444" opacity="0.24" />
              <circle cx={aiFocus.detect.x} cy={aiFocus.detect.y} r="20" fill="#ef4444" stroke="#fff7ed" strokeWidth="5" />
              <text x={aiFocus.detect.x + 29} y={aiFocus.detect.y - 10} fill="#7f1d1d" fontSize="13" fontWeight="900">Detect</text>
              <text x={aiFocus.detect.x + 29} y={aiFocus.detect.y + 7} fill="#7f1d1d" fontSize="11" fontWeight="800">{aiFocus.detect.title}</text>

              <circle className={aiPhase === "running" ? "park-command-pulse" : ""} cx="502" cy="344" r="28" fill="#22d3ee" stroke="#083344" strokeWidth="5" />
              <text x="502" y="349" textAnchor="middle" fill="#082f49" fontSize="12" fontWeight="900">AI</text>
              <text x="502" y="390" textAnchor="middle" fill="#083344" fontSize="11" fontWeight="900">
                {["Predict", "Decide", "Govern", "Emit", "Observe", "Learn"][Math.min(5, visualStepIndex)]}
              </text>
              {(proactiveRunTelemetry || runTelemetry || aiPhase === "running") && (
                <g transform="translate(528 315)">
                  <rect width="218" height="76" rx="11" fill="#f8fafc" stroke={runtimeCalloutTone} strokeWidth="3" opacity="0.96" />
                  <circle className={aiPhase === "running" ? "park-node-pulse-svg" : ""} cx="16" cy="17" r="7" fill={runtimeCalloutTone} />
                  <text x="30" y="20" fill="#0f172a" fontSize="10" fontWeight="900">
                    {runtimeLabel.slice(0, 30)}
                  </text>
                  <text x="12" y="38" fill="#475569" fontSize="9" fontWeight="800">
                    {runtimeModel.slice(0, 34)}
                  </text>
                  <text x="12" y="54" fill="#334155" fontSize="9" fontWeight="900">
                    Gate: {runtimeGate.slice(0, 28)}
                  </text>
                  <text x="12" y="68" fill="#334155" fontSize="9" fontWeight="900">
                    Memory: {runtimeMemory.slice(0, 26)}
                  </text>
                </g>
              )}

              <g transform="translate(46 86)">
                <rect width="244" height="72" rx="12" fill="#f8fafc" stroke="#0891b2" strokeWidth="3" opacity="0.96" />
                <text x="12" y="18" fill="#0e7490" fontSize="10" fontWeight="900">{customActionOverlay.intentSummary ? "Gemini understood" : "Custom action mix"}</text>
                <text x="12" y="36" fill="#0f172a" fontSize="11" fontWeight="900">
                  {customActionOverlay.headline.slice(0, 34)}
                </text>
                <text x="12" y="53" fill="#475569" fontSize="9" fontWeight="800">
                  {(customActionOverlay.primaryAction ?? customActionOverlay.routes.map((route) => `${route.destination}${typeof route.share === "number" ? ` ${Math.round(route.share * 100)}%` : ""}`).join(" / ")).slice(0, 48)}
                </text>
                <text x="12" y="66" fill="#475569" fontSize="9" fontWeight="800">
                  {customActionOverlay.incidentType ? customActionOverlay.incidentType.replaceAll("_", " ").slice(0, 42) : customActionOverlay.avoidZones.length ? `Avoid: ${customActionOverlay.avoidZones.map((zone) => zone.label).join(", ")}` : customActionOverlay.holdShare ? `Hold share ${Math.round(customActionOverlay.holdShare * 100)}%` : "Map follows selected action, not a fixed tree"}
                </text>
              </g>

              {customActionOverlay.avoidZones.map((zone) => (
                <g key={`avoid-${zone.id}`}>
                  <circle className={showBeforeState ? "park-node-pulse-svg" : ""} cx={zone.point.x} cy={zone.point.y} r={showAfterState ? "44" : "58"} fill={showAfterState ? "#10b981" : "#ef4444"} opacity={showAfterState ? "0.16" : "0.18"} />
                  <circle cx={zone.point.x} cy={zone.point.y} r="30" fill="none" stroke={showAfterState ? "#10b981" : "#ef4444"} strokeWidth="7" />
                  {showAfterState ? (
                    <path d={`M${zone.point.x - 18} ${zone.point.y + 1} L${zone.point.x - 5} ${zone.point.y + 15} L${zone.point.x + 22} ${zone.point.y - 17}`} stroke="#10b981" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                  ) : (
                    <path d={`M${zone.point.x - 22} ${zone.point.y - 22} L${zone.point.x + 22} ${zone.point.y + 22} M${zone.point.x + 22} ${zone.point.y - 22} L${zone.point.x - 22} ${zone.point.y + 22}`} stroke="#ef4444" strokeWidth="7" strokeLinecap="round" />
                  )}
                  <g transform={`translate(${zone.point.x - 76} ${zone.point.y + 42})`}>
                    <rect width="152" height="36" rx="9" fill={showAfterState ? "#ecfdf5" : "#fef2f2"} stroke={showAfterState ? "#10b981" : "#ef4444"} strokeWidth="3" />
                    <text x="10" y="15" fill={showAfterState ? "#064e3b" : "#991b1b"} fontSize="10" fontWeight="900">{showAfterState ? "Intake paused" : "Avoid zone"}</text>
                    <text x="10" y="29" fill={showAfterState ? "#064e3b" : "#7f1d1d"} fontSize="9" fontWeight="800">{zone.label}</text>
                  </g>
                </g>
              ))}

              {showDecisionPhase && customActionOverlay.routes.map((route, index) => {
                const offset = index * 22;
                const controlX = (customActionOverlay.source.x + route.point.x) / 2 - 30 + offset;
                const controlY = Math.min(customActionOverlay.source.y, route.point.y) - 98 - index * 12;
                const path = `M${customActionOverlay.source.x} ${customActionOverlay.source.y} C${controlX} ${controlY}, ${controlX} ${controlY}, ${route.point.x} ${route.point.y}`;
                return (
                  <g key={`custom-route-${route.id}`}>
                    <path d={path} stroke="#083344" strokeWidth="12" strokeLinecap="round" fill="none" opacity={showAfterState ? "0.22" : "0.08"} />
                    <path className={showAfterState ? "park-flow-line" : ""} d={path} stroke={showAfterState ? (index === 0 ? "#22d3ee" : "#38bdf8") : "#94a3b8"} strokeWidth={showAfterState ? (index === 0 ? "7" : "5") : "4"} strokeDasharray={showAfterState ? undefined : "8 12"} strokeLinecap="round" fill="none" opacity={showAfterState ? "0.9" : "0.55"} />
                    <circle cx={route.point.x} cy={route.point.y} r={showAfterState ? "22" : "14"} fill={showAfterState ? "#ecfeff" : "#f8fafc"} stroke={showAfterState ? "#0891b2" : "#94a3b8"} strokeWidth="5" />
                    {showAfterState && (
                      <>
                        <circle className="park-node-pulse-svg" cx={route.point.x - 16} cy={route.point.y + 26} r="5" fill="#22d3ee" />
                        <circle className="park-node-pulse-svg" cx={route.point.x + 2} cy={route.point.y + 30} r="5" fill="#22d3ee" />
                        <circle className="park-node-pulse-svg" cx={route.point.x + 20} cy={route.point.y + 25} r="5" fill="#22d3ee" />
                      </>
                    )}
                    <text x={route.point.x} y={route.point.y + 4} textAnchor="middle" fill="#0e7490" fontSize="10" fontWeight="900">
                      {typeof route.share === "number" ? `${Math.round(route.share * 100)}` : index + 1}
                    </text>
                    <g transform={`translate(${route.point.x + 24} ${route.point.y - 30})`}>
                      <rect width="132" height="42" rx="9" fill="#ecfeff" stroke="#0891b2" strokeWidth="2" opacity="0.94" />
                      <text x="9" y="16" fill="#164e63" fontSize="10" fontWeight="900">{route.destination.slice(0, 18)}</text>
                      <text x="9" y="31" fill="#164e63" fontSize="9" fontWeight="800">
                        {showAfterState ? (typeof route.share === "number" ? `${Math.round(route.share * 100)}% moving now` : "guests moving") : "planned target"}
                      </text>
                    </g>
                  </g>
                );
              })}

              {showDecisionPhase && customActionOverlay.staffMoves.map((move) => {
                const path = `M${move.from.x} ${move.from.y} C${(move.from.x + move.to.x) / 2} ${Math.max(70, Math.min(move.from.y, move.to.y) - 80)}, ${(move.from.x + move.to.x) / 2} ${Math.max(70, Math.min(move.from.y, move.to.y) - 80)}, ${move.to.x} ${move.to.y}`;
                return (
                  <g key={`staff-move-${move.id}`}>
                    <path d={path} stroke="#064e3b" strokeWidth="10" strokeLinecap="round" fill="none" opacity={showAfterState ? "0.18" : "0.08"} />
                    <path className={showAfterState ? "park-flow-line" : ""} d={path} stroke={showAfterState ? "#10b981" : "#94a3b8"} strokeWidth={showAfterState ? "6" : "4"} strokeDasharray={showAfterState ? undefined : "8 12"} strokeLinecap="round" fill="none" opacity={showAfterState ? "0.9" : "0.55"} />
                    <circle cx={move.to.x} cy={move.to.y} r="15" fill="#ecfdf5" stroke="#059669" strokeWidth="5" />
                    {showAfterState && <circle className="park-node-pulse-svg" cx={move.to.x - 23} cy={move.to.y - 7} r="7" fill="#10b981" />}
                    <g transform={`translate(${move.to.x + 20} ${move.to.y + 18})`}>
                      <rect width="134" height="38" rx="9" fill="#ecfdf5" stroke="#059669" strokeWidth="2" />
                      <text x="9" y="15" fill="#064e3b" fontSize="10" fontWeight="900">{showAfterState ? "Staff arrived" : "Staff move"}</text>
                      <text x="9" y="29" fill="#064e3b" fontSize="9" fontWeight="800">{move.count ? `${move.count} ` : ""}{move.role}</text>
                    </g>
                  </g>
                );
              })}

              {showDecisionPhase && customActionOverlay.hvacZones.map((zone) => (
                <g key={`hvac-${zone.id}`}>
                  <circle className={showAfterState ? "park-node-pulse-svg" : ""} cx={zone.point.x} cy={zone.point.y} r="46" fill="#f59e0b" opacity={showAfterState ? "0.2" : "0.1"} />
                  <circle cx={zone.point.x} cy={zone.point.y} r="20" fill="#fffbeb" stroke="#d97706" strokeWidth="5" />
                  <text x={zone.point.x} y={zone.point.y + 4} textAnchor="middle" fill="#78350f" fontSize="9" fontWeight="900">{zone.setpoint ? "HVAC" : "CTRL"}</text>
                  <text x={zone.point.x + 26} y={zone.point.y - 18} fill="#78350f" fontSize="10" fontWeight="900">
                    {showAfterState ? (zone.setpoint ? `${zone.setpoint}F applied` : "applied") : zone.setpoint ? `${zone.setpoint}F plan` : "planned"}
                  </text>
                </g>
              ))}

              {showEmitPhase && customActionOverlay.receiverActions.map((action, index) => {
                const tone = action.channel === "guest_app" ? "#0891b2" : action.channel === "worker_device" ? "#059669" : "#d97706";
                const yOffset = 64 + index * 18;
                return (
                  <g key={`receiver-action-${action.id}`}>
                    <path className="park-flow-line" d={`M502 344 C${Math.round((502 + action.point.x) / 2)} ${Math.max(76, action.point.y - yOffset)}, ${Math.round((502 + action.point.x) / 2)} ${Math.max(76, action.point.y - yOffset)}, ${action.point.x} ${action.point.y}`} stroke={tone} strokeWidth="5" strokeLinecap="round" fill="none" opacity="0.72" />
                    <circle cx={action.point.x} cy={action.point.y} r="14" fill="#f8fafc" stroke={tone} strokeWidth="5" />
                    <g transform={`translate(${Math.min(760, action.point.x + 18)} ${Math.max(82, action.point.y - 18)})`}>
                      <rect width="142" height="34" rx="8" fill="#f8fafc" stroke={tone} strokeWidth="2" opacity="0.94" />
                      <text x="8" y="14" fill="#0f172a" fontSize="9" fontWeight="900">{action.label.slice(0, 20)}</text>
                      <text x="8" y="27" fill="#475569" fontSize="8" fontWeight="800">{(action.status || action.channel).slice(0, 22)}</text>
                    </g>
                  </g>
                );
              })}

              <path className="park-flow-line" d={`M${aiFocus.detect.x} ${aiFocus.detect.y} C664 250 581 284 502 344`} stroke="#ef4444" strokeWidth="5" strokeLinecap="round" fill="none" opacity="0.8" />
              {showDecisionPhase && (
                <g>
                  <path d={`M502 344 C590 232 671 215 ${aiFocus.detect.x} ${aiFocus.detect.y}`} stroke="#f87171" strokeDasharray="12 12" strokeLinecap="round" strokeWidth="4" fill="none" opacity="0.68" />
                  <path d="M502 344 C456 282 412 248 356 227" stroke="#94a3b8" strokeDasharray="8 12" strokeLinecap="round" strokeWidth="4" fill="none" opacity="0.62" />
                  <g transform="translate(335 178)">
                    <rect width="164" height="42" rx="9" fill="#f8fafc" stroke="#64748b" strokeWidth="2" opacity="0.94" />
	                    <text x="10" y="17" fill="#334155" fontSize="10" fontWeight="900">Candidate rejected</text>
	                    <text x="10" y="32" fill="#475569" fontSize="9" fontWeight="800">{(customActionOverlay.rejectedOption ?? "unsafe or lower utility").slice(0, 28)}</text>
                  </g>
                </g>
              )}
              {showGovernPhase && (
                <g transform="translate(438 276)">
                  <rect width="132" height="44" rx="10" fill="#fffbeb" stroke="#f59e0b" strokeWidth="3" />
                  <text x="12" y="18" fill="#78350f" fontSize="10" fontWeight="900">Safety check</text>
                  <text x="12" y="33" fill="#78350f" fontSize="10" fontWeight="800">{runtimeGate.slice(0, 18)}</text>
                </g>
              )}
              {showEmitPhase && (
                <g>
                  <path className="park-flow-line" d={`M502 344 C425 306 324 275 ${aiFocus.guest.x} ${aiFocus.guest.y}`} stroke="#22d3ee" strokeWidth="5" strokeLinecap="round" fill="none" opacity="0.78" />
                  <path className="park-flow-line" d={`M502 344 C570 408 633 459 ${aiFocus.worker.x} ${aiFocus.worker.y}`} stroke="#10b981" strokeWidth="5" strokeLinecap="round" fill="none" opacity="0.82" />
                  <path className="park-flow-line" d={`M502 344 C612 322 700 295 ${aiFocus.ops.x} ${aiFocus.ops.y}`} stroke="#f59e0b" strokeWidth="5" strokeLinecap="round" fill="none" opacity="0.82" />
                </g>
              )}

              {showEmitPhase && <g transform={`translate(${aiFocus.guest.x} ${aiFocus.guest.y})`}>
                <rect width="126" height="42" rx="10" fill="#ecfeff" stroke="#0891b2" strokeWidth="3" />
                <text x="11" y="17" fill="#164e63" fontSize="10" fontWeight="900">{aiFocus.guest.title}</text>
                <text x="11" y="32" fill="#164e63" fontSize="10" fontWeight="800">{movedGuests ? `${movedGuests} moved` : "movement pending"}</text>
              </g>}
              {showEmitPhase && <g transform={`translate(${aiFocus.worker.x} ${aiFocus.worker.y})`}>
                <rect width="126" height="42" rx="10" fill="#ecfdf5" stroke="#059669" strokeWidth="3" />
                <text x="11" y="17" fill="#064e3b" fontSize="10" fontWeight="900">{aiFocus.worker.title}</text>
                <text x="11" y="32" fill="#064e3b" fontSize="10" fontWeight="800">{dispatchTotal || 3} dispatches</text>
              </g>}
              {showEmitPhase && <g transform={`translate(${aiFocus.ops.x} ${aiFocus.ops.y})`}>
                <rect width="118" height="42" rx="10" fill="#fffbeb" stroke="#d97706" strokeWidth="3" />
                <text x="11" y="17" fill="#78350f" fontSize="10" fontWeight="900">{aiFocus.ops.title}</text>
                <text x="11" y="32" fill="#78350f" fontSize="10" fontWeight="800">{densityDelta} density</text>
              </g>}

              {showEmitPhase && (
                <g>
                  <circle className="park-node-pulse-svg" cx={aiFocus.guest.x + 22} cy={aiFocus.guest.y + 52} r="7" fill="#22d3ee" />
                  <circle className="park-node-pulse-svg" cx={aiFocus.worker.x + 22} cy={aiFocus.worker.y + 52} r="7" fill="#10b981" />
                </g>
              )}

              {hasReceiverAck && (
                <g>
                  <path className="park-flow-line" d={`M${aiFocus.detect.x} ${aiFocus.detect.y} C620 320 482 340 ${aiFocus.guest.x + 70} ${aiFocus.guest.y + 22}`} stroke="#10b981" strokeWidth="9" strokeLinecap="round" fill="none" opacity="0.55" />
                  <path className="park-flow-line" d={`M${aiFocus.worker.x + 62} ${aiFocus.worker.y + 20} C632 450 662 392 ${aiFocus.detect.x - 18} ${aiFocus.detect.y + 18}`} stroke="#059669" strokeWidth="7" strokeLinecap="round" fill="none" opacity={workerAcked ? "0.7" : "0.28"} />
                  <g transform={`translate(${Math.max(36, aiFocus.detect.x - 86)} ${Math.min(548, aiFocus.detect.y + 72)})`}>
                    <rect width="210" height="46" rx="10" fill="#ecfdf5" stroke="#10b981" strokeWidth="3" />
                    <text x="11" y="17" fill="#064e3b" fontSize="10" fontWeight="900">Live receiver reaction</text>
                    <text x="11" y="33" fill="#064e3b" fontSize="10" fontWeight="800">{receiverAckLabel}</text>
                  </g>
                </g>
              )}

              {showLiveObservePhase && (
                <g>
                  <circle cx={aiFocus.detect.x} cy={aiFocus.detect.y} r="58" fill="#10b981" opacity="0.14" />
                  <circle cx={aiFocus.guest.x} cy={aiFocus.guest.y} r="64" fill="#22d3ee" opacity="0.12" />
                  <path d={`M${aiFocus.detect.x} ${aiFocus.detect.y} C${(aiFocus.detect.x + aiFocus.guest.x) / 2} ${aiFocus.detect.y - 48} ${(aiFocus.detect.x + aiFocus.guest.x) / 2} ${aiFocus.guest.y + 48} ${aiFocus.guest.x} ${aiFocus.guest.y}`} stroke="#10b981" strokeWidth="12" strokeLinecap="round" fill="none" opacity="0.22" />
                  <g transform="translate(548 378)">
                    <rect width="184" height="46" rx="10" fill="#ecfdf5" stroke="#10b981" strokeWidth="3" />
                    <text x="11" y="17" fill="#064e3b" fontSize="10" fontWeight="900">After</text>
                    <text x="11" y="33" fill="#064e3b" fontSize="10" fontWeight="800">{stateImpactLine.slice(0, 28)}</text>
                  </g>
                  <text x="548" y="426" fill="#064e3b" fontSize="13" fontWeight="900">{beforeAfterLine.slice(0, 44)}</text>
                  <text x="548" y="444" fill="#064e3b" fontSize="11" fontWeight="800">Learn: {takeRateLabel}; {analyticsLabel}</text>
                  <g transform="translate(296 528)">
                    <rect width="430" height="38" rx="10" fill="#f8fafc" stroke="#0f172a" strokeWidth="2" opacity="0.94" />
                    {[
                      ["Plan", runtimeModel],
                      ["Gate", runtimeGate],
                      ["Emit", `${dispatchTotal || 0}`],
                      ["Learn", runtimeMemory],
                    ].map(([label, value], index) => (
                      <g key={label} transform={`translate(${index * 106 + 10} 8)`}>
                        <text x="0" y="8" fill="#64748b" fontSize="7.5" fontWeight="900">{label}</text>
                        <text x="0" y="22" fill="#0f172a" fontSize="9" fontWeight="900">{String(value).slice(0, 14)}</text>
                      </g>
                    ))}
                  </g>
                </g>
              )}
              {showLiveLearnPhase && (
                <g transform="translate(448 392)">
                  <rect width="220" height="52" rx="10" fill="#f5f3ff" stroke="#8b5cf6" strokeWidth="3" />
                  <text x="12" y="16" fill="#5b21b6" fontSize="10" fontWeight="900">Mongo + BigQuery receipt</text>
                  <text x="12" y="30" fill="#5b21b6" fontSize="9" fontWeight="800">{runtimeMemory.slice(0, 28)}</text>
                  <text x="12" y="44" fill="#5b21b6" fontSize="8.5" fontWeight="800">{learnedBiasLabel.slice(0, 42)}</text>
                </g>
              )}
            </g>
          )}
        </svg>

        {compact && showCompactPanels && (
          <>
            <BeforeAfterReplayToggle value={replayView} onChange={setReplayView} hasAction={hasActionPayload} />
            <RuntimeProofBadge
              runtimeLabel={runtimeLabel}
              runtimeModel={runtimeModel}
              runtimeGate={runtimeGate}
              runtimeMemory={runtimeMemory}
              isLive={Boolean(runtimeIsLive)}
              fallbackReason={runtimeProof?.fallback_reason ?? (runTelemetry?.planner?.gemini_ready === false && runTelemetry?.planner?.attempted_gemini ? "fallback" : null)}
            />
            <CascadeTimelineOverlay rows={cascadeRows} />
            {showAfterState && (
              <StateMutationBadge
                source={customActionOverlay.source}
                routes={customActionOverlay.routes}
                staffMoves={customActionOverlay.staffMoves}
                hvacZones={customActionOverlay.hvacZones}
                dispatchCount={dispatchTotal}
                response={deliveryResponse}
              />
            )}
            <LearningDeltaBadge telemetry={proactiveRunTelemetry} runTelemetry={runTelemetry} response={deliveryResponse} />
            <CompactReceiverDemo
              key={`${scenario.key}-phones`}
              scenario={scenario}
              aiPhase={aiPhase}
              dispatches={dispatches}
              response={deliveryResponse}
              onReceiverAck={onReceiverAck}
            />
            <ReceiverTray
              key={scenario.key}
              scenario={scenario}
              aiPhase={aiPhase}
              dispatches={dispatches}
              response={deliveryResponse}
            />
          </>
        )}

        {!compact && <div className="absolute bottom-5 left-5 right-5 z-30 grid gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-white/70 bg-white/90 p-3 shadow-xl shadow-stone-950/20 backdrop-blur">
            <div className="text-[10px] font-black uppercase tracking-widest text-stone-500">Busiest zone</div>
            <div className="mt-1 text-lg font-black text-stone-950">{busiestZone?.name ?? "Stable"}</div>
            <div className="mt-1 text-xs text-stone-600">{busiestZone ? `${pct(busiestZone.density)} density / ${busiestZone.currentGuests.toLocaleString()} guests` : "No pressure"}</div>
          </div>
          <div className="rounded-lg border border-white/70 bg-white/90 p-3 shadow-xl shadow-stone-950/20 backdrop-blur">
            <div className="text-[10px] font-black uppercase tracking-widest text-stone-500">Queue load</div>
            <div className="mt-1 text-lg font-black text-stone-950">{totalQueue.toLocaleString()}</div>
            <div className="mt-1 text-xs text-stone-600">Guests waiting across top attractions</div>
          </div>
          <div className="rounded-lg border border-white/70 bg-white/90 p-3 shadow-xl shadow-stone-950/20 backdrop-blur">
            <div className="text-[10px] font-black uppercase tracking-widest text-stone-500">Decision pressure</div>
            <div className={scenario.riskLevel === "HIGH" ? "mt-1 text-lg font-black text-red-700" : "mt-1 text-lg font-black text-amber-700"}>{scenario.riskLevel}</div>
            <div className="mt-1 text-xs text-stone-600">{Math.round(scenario.confidence * 100)}% confidence</div>
          </div>
        </div>}

        {!compact && <div className="absolute right-5 top-24 z-30 hidden w-60 rounded-lg border border-white/70 bg-white/90 p-3 text-stone-800 shadow-xl shadow-stone-950/20 backdrop-blur lg:block">
          <div className="text-[10px] font-black uppercase tracking-widest text-stone-500">Current map layer</div>
          <div className="mt-1 text-sm font-black text-stone-950">{MAP_LAYERS.find((layer) => layer.id === activeLayer)?.label}</div>
          <div className="mt-1 text-[11px] leading-relaxed text-stone-600">{MAP_LAYERS.find((layer) => layer.id === activeLayer)?.detail}</div>
          <div className="mt-2 grid gap-2 text-[11px] font-bold">
            <div className="flex items-center justify-between"><span>Attractions</span><span>{layerStats.attractions}</span></div>
            <div className="flex items-center justify-between"><span>Queues</span><span>{layerStats.queues}</span></div>
            <div className="flex items-center justify-between"><span>Guest groups</span><span>{layerStats.guests}</span></div>
            <div className="flex items-center justify-between"><span>Support agents</span><span>{layerStats.support}</span></div>
            <div className="flex items-center justify-between"><span>Ops points</span><span>{layerStats.operations}</span></div>
            <div className="flex items-center justify-between"><span>Live signals</span><span>{layerStats.signals}</span></div>
          </div>
          {operatingClock && (
            <div className="mt-3 rounded border border-cyan-200 bg-cyan-50 p-2 text-[11px] leading-relaxed text-cyan-950">
              <div className="font-black uppercase tracking-widest">Operating clock</div>
              <div className="mt-1 font-bold">{operatingClock.phase.label}</div>
              <div className="mt-1">Intent: {operatingClock.guestIntent.dominantIntent}</div>
              <div className="mt-1">Staff delay {operatingClock.staffLifecycle.redeployDelayMinutes}m · feedback lag {operatingClock.guestFeedbackLoop.complaintLagMinutes}m</div>
            </div>
          )}
          <div className="mt-3 rounded border border-violet-200 bg-violet-50 p-2 text-[11px] leading-relaxed text-violet-950">
            <div className="font-black uppercase tracking-widest">Map time-lapse</div>
            <div className="mt-1 font-bold">{timeLensTitle(timeLens)}</div>
            <div className="mt-1">Past ghost, current frame, or projected +15m pressure rendered over the same physical park map.</div>
          </div>
          {nextShowtime && (
            <div className="mt-3 rounded border border-fuchsia-200 bg-fuchsia-50 p-2 text-[11px] leading-relaxed text-fuchsia-950">
              <div className="font-black uppercase tracking-widest">Showtime traffic solver</div>
              <div className="mt-1 font-bold">{nextShowtime.name} · {nextShowtime.startTime}</div>
              <div className="mt-1">{activeShowtimes.length ? `${activeShowtimes.length} active wave${activeShowtimes.length > 1 ? "s" : ""}` : "Next scheduled wave"} · risk {pct(showtimeRisk)}</div>
              <div className="mt-1">{nextShowtime.solvedByPolicy ? "Mitigation active" : nextShowtime.solution}</div>
            </div>
          )}
          {accessFairness && (
            <div className="mt-3 rounded border border-red-200 bg-red-50 p-2 text-[11px] leading-relaxed text-red-950">
              <div className="font-black uppercase tracking-widest">VIP/Fast Lane fairness</div>
              <div className="mt-1 font-bold">Public complaint risk {pct(accessFairness.publicComplaintRiskPct)}</div>
              <div className="mt-1">Premium lane {pct(accessFairness.premiumLaneSharePct)} creates +{accessFairness.standbyDelayDeltaMins}m standby delay.</div>
              <div className="mt-1">{accessFairness.solvedByPolicy ? "Merge cap active" : accessFairness.mitigationControls[0]}</div>
            </div>
          )}
          <div className="mt-3 rounded border border-stone-200 bg-stone-50 p-2 text-[11px] leading-relaxed text-stone-600">
            {physicalMap.realismNotes[0] ?? "Physical constraints are loaded from the live park state."}
          </div>
        </div>}
      </div>

      {!compact && <aside className="grid content-start gap-4">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Live command</div>
          <h2 className="mt-1 text-3xl font-black leading-tight text-slate-100">{customActionOverlay.headline}</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-400">{proof.signal}</p>
        </div>

        <ActionBusPanel telemetry={runTelemetry} isRunning={isRunning} />

        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">What changes</div>
          <div className="mt-3 grid gap-3">
            {actionPreview.length ? actionPreview.map((action, index) => (
              <div key={`${action.owner}-${action.action}`} className="grid grid-cols-[2rem_1fr] gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded bg-slate-950 text-xs font-black text-cyan-300">{index + 1}</div>
                <div>
                  <div className="text-sm font-bold text-slate-200">{action.owner}</div>
                  <div className="mt-1 text-xs leading-relaxed text-slate-500">{action.action}</div>
                </div>
              </div>
            )) : (
              <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm leading-relaxed text-slate-400">
                Action cards appear only after Gemini returns a custom plan.
              </div>
            )}
          </div>
        </div>

        <div className="grid gap-3">
          {metricPreview.map((metric) => (
            <div key={metric.label} className={`rounded-lg border p-3 ${toneClass(metric.tone)}`}>
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-black uppercase tracking-widest opacity-70">{metric.label}</div>
                <div className="text-xl font-black">{metric.value}</div>
              </div>
              <div className="mt-1 text-xs opacity-75">{metric.detail}</div>
            </div>
          ))}
        </div>
      </aside>}
    </section>
  );
}
