import type { ScenarioKey } from "@/types/platform";

export type HeroStoryKey = "parade_ride_failure" | "food_heat_surge" | "storm_shelter_split" | "staffing_fairness_crunch";

export type CanonicalHeroStory = {
  key: HeroStoryKey;
  scenarioKey: ScenarioKey;
  label: string;
  title: string;
  incident: string;
  operatorPrompt: string;
  stakes: string[];
  proofFocus: string[];
  outcomeTarget: string;
};

export const CANONICAL_HERO_STORIES: CanonicalHeroStory[] = [
  {
    key: "parade_ride_failure",
    scenarioKey: "ride_down",
    label: "Hero 1",
    title: "Ride failure during parade release",
    incident: "Dragon Coaster goes into maintenance hold while the parade releases families into the same corridor.",
    operatorPrompt: "Dragon Coaster is down during parade release. Keep guests safe, avoid overloading Indoor Launch, stage staff, and prepare bounded guest and worker actions.",
    stakes: ["Coaster Plaza density", "alternate ride spillback", "family recovery", "maintenance gate"],
    proofFocus: ["ride status", "crowd split", "policy gate", "receiver ack"],
    outcomeTarget: "Lower Coaster Plaza pressure without creating a second bottleneck.",
  },
  {
    key: "food_heat_surge",
    scenarioKey: "food_spike",
    label: "Hero 2",
    title: "Food backlog plus heat-care weak signal",
    incident: "Mobile pickup backs up while heat-fatigue notes and dwell time rise around Food Court A.",
    operatorPrompt: "Food Court A is overloaded and heat-care notes are rising. Shape demand safely, protect inventory truth, and stage worker support without over-promising guests.",
    stakes: ["pickup ETA", "inventory truth", "care response", "revenue protection"],
    proofFocus: ["mobile orders", "menu suppression", "worker task", "take rate"],
    outcomeTarget: "Reduce pickup promises and move demand before guest-care cases spike.",
  },
  {
    key: "storm_shelter_split",
    scenarioKey: "storm_response",
    label: "Hero 3",
    title: "Storm shelter split with energy constraint",
    incident: "Outdoor queues need shelter while indoor zones and building systems are close to peak pressure.",
    operatorPrompt: "Storm risk is rising. Split guests across shelter zones, protect accessibility routes, and only shed energy where comfort and safety stay inside policy.",
    stakes: ["outdoor exposure", "shelter comfort", "BMS action", "accessibility route"],
    proofFocus: ["weather feed", "indoor density", "equipment command", "approval gate"],
    outcomeTarget: "Move exposed guests indoors without turning one shelter into a crush point.",
  },
  {
    key: "staffing_fairness_crunch",
    scenarioKey: "staff_shortage",
    label: "Hero 4",
    title: "Staff shortage collides with fairness complaints",
    incident: "Callouts, break windows, and Fast Lane complaints collide while guest flow still needs action.",
    operatorPrompt: "Staff callouts and standby fairness complaints are rising. Protect breaks, avoid individual profiling, and compare the least harmful bounded action.",
    stakes: ["break protection", "fairness perception", "certified coverage", "operator review"],
    proofFocus: ["staff ledger", "fairness policy", "branch comparison", "memory update"],
    outcomeTarget: "Keep service moving while preserving labor and fairness constraints.",
  },
];

export function canonicalHeroStoryForScenario(scenarioKey: ScenarioKey) {
  return CANONICAL_HERO_STORIES.find((story) => story.scenarioKey === scenarioKey) ?? CANONICAL_HERO_STORIES[0];
}
