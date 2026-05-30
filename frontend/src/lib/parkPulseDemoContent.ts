import type { DeliveryDispatch, DemoScenario, EvalScore, PolicyArea, ScenarioKey } from "@/types/platform";

const EY_EVALS: EvalScore[] = [
  { label: "Digital twin confidence", score: 86, detail: "Shows the assumed horizon, projected state movement, and uncertainty before dispatch." },
  { label: "Message timing", score: 88, detail: "Checks whether guest, worker, and signage payloads land before pressure peaks." },
  { label: "Privacy-safe personalization", score: 92, detail: "Targets aggregate guest segments without exposing individual identity or PII." },
  { label: "Data completeness", score: 81, detail: "Surfaces stale, partial, or missing feeds before the recommendation is trusted." },
];

const EY_EXPERIENCE_MODELS: Record<ScenarioKey, NonNullable<DemoScenario["experienceModel"]>> = {
  ride_down: {
    connectedData: [
      { source: "Ride PLC + downtime feed", signal: "Dragon Coaster maintenance hold / 44m current estimate", status: "live" },
      { source: "Queue camera heat map", signal: "540 guests still clustered near coaster exit", status: "live" },
      { source: "Staff roster", signal: "2 crowd-control roles available within 10m", status: "watch" },
      { source: "Mobile app telemetry", signal: "Thrill-rider cohort still opening coaster page", status: "live" },
    ],
    digitalTwin: {
      horizon: "Next 30 minutes",
      prediction: "A single alternate-ride push overloads Indoor Launch, while a split plan lowers coaster-zone density without creating a second spillback.",
      confidence: 86,
      assumptions: ["Ride remains closed for at least 40 minutes", "Indoor Launch promotion is capped", "Two staff accept redeployment"],
      projectedMetrics: [
        { label: "Coaster zone density", before: "94%", after: "76%", tone: "ok" },
        { label: "Indoor Launch wait", before: "55m", after: "58m capped", tone: "watch" },
        { label: "Guest frustration", before: "HIGH", after: "MED", tone: "ok" },
      ],
    },
    smartActions: [
      { channel: "guest_app", target: "Guests near Dragon Coaster", payload: "Dragon Coaster is delayed. Sky Drop, arcade challenge, and Theater B have faster options nearby.", guardrail: "No reopening promise or blanket compensation." },
      { channel: "digital_signage", target: "Coaster Plaza signs", payload: "Dragon Coaster paused. Use Sky Drop, Arcade, or Theater B routes.", guardrail: "Maintenance hold remains visible." },
      { channel: "worker_device", target: "Crowd-control team", payload: "Move 2 staff to coaster exit and split guests toward arcade and theater paths.", guardrail: "Do not pull certified ride operators below minimum." },
    ],
    guestSegments: [
      { segment: "Thrill riders", trigger: "Opened coaster page twice in 10m", message: "Sky Drop has a shorter thrill route from your current zone.", incentive: "Priority challenge points for Sky Drop scan-in", privacy: "Segment-level targeting only." },
      { segment: "Families exiting queue", trigger: "Leaving Dragon queue footprint", message: "Theater B and Shade Garden are closest low-wait recovery options.", privacy: "No guest identity shown to operators." },
    ],
    dataReadiness: [
      { source: "Ride status", status: "ready", latency: "8s", coverage: "100%", impact: "Safe to block reopening suggestions." },
      { source: "Guest density", status: "ready", latency: "22s", coverage: "91%", impact: "Strong enough for split-routing projection." },
      { source: "Staff acknowledgments", status: "watch", latency: "2m", coverage: "68%", impact: "Requires follow-up if no worker ack arrives." },
    ],
  },
  staff_shortage: {
    connectedData: [
      { source: "Workforce system", signal: "18 callouts across rides, food, and guest flow", status: "live" },
      { source: "Training tags", signal: "Cross-trained cashier and queue roles available", status: "live" },
      { source: "Break policy ledger", signal: "Two teams approaching protected break windows", status: "live" },
      { source: "Queue telemetry", signal: "Dispatch frequency slipping on lower-demand rides", status: "watch" },
    ],
    digitalTwin: {
      horizon: "Next 45 minutes",
      prediction: "Protecting certified coverage and slowing lower-demand lanes prevents a broader service collapse with smaller guest impact.",
      confidence: 83,
      assumptions: ["Break windows stay hard constraints", "Cross-trained staff accept temporary moves", "Snack Stand C can pause without accessibility impact"],
      projectedMetrics: [
        { label: "Break violations", before: "2 at risk", after: "0 allowed", tone: "ok" },
        { label: "Food wait", before: "38m", after: "26m", tone: "ok" },
        { label: "Low-demand ride wait", before: "+8m", after: "+14m", tone: "watch" },
      ],
    },
    smartActions: [
      { channel: "worker_device", target: "Cross-trained staff", payload: "Temporary move: Food Court 1 pickup support for 30 minutes.", guardrail: "Protected breaks and certification minimums cannot be overridden." },
      { channel: "guest_app", target: "Guests near lower-demand rides", payload: "Some attractions are running slower while teams rebalance service. Nearby shows have shorter waits.", guardrail: "No pressure on workers or individual staff details." },
      { channel: "digital_signage", target: "Snack Stand C", payload: "Temporarily closed. Food Court 1 and Mobile Pickup remain open.", guardrail: "Accessible food routes remain available." },
    ],
    guestSegments: [
      { segment: "Meal-seeking guests", trigger: "Within 250m of overloaded food queue", message: "Food Court 1 pickup support is opening now; nearby stands may pause briefly.", privacy: "Location bucket only, no individual history." },
      { segment: "Show-compatible groups", trigger: "Near low-demand ride with rising wait", message: "Theater B has immediate seating while ride staffing rebalances.", incentive: "Show badge points", privacy: "Opt-in app segment." },
    ],
    dataReadiness: [
      { source: "Staff roster", status: "ready", latency: "15s", coverage: "96%", impact: "Redeployment can respect training tags." },
      { source: "Break ledger", status: "ready", latency: "real time", coverage: "100%", impact: "Hard gate for worker-wellbeing eval." },
      { source: "Ride wait feed", status: "watch", latency: "3m", coverage: "82%", impact: "Projection should refresh before second redeployment." },
    ],
  },
  food_spike: {
    connectedData: [
      { source: "Mobile order system", signal: "143 open orders and 34m pickup ETA", status: "live" },
      { source: "Inventory feed", signal: "Chicken tenders and bottled drinks below threshold", status: "live" },
      { source: "Kitchen load model", signal: "Food Court B at 42% capacity", status: "live" },
      { source: "Guest movement heat map", signal: "Adventure Zone lunch cluster still growing", status: "watch" },
    ],
    digitalTwin: {
      horizon: "Next 20 minutes",
      prediction: "Suppressing constrained SKUs and promoting Food Court B preserves revenue while preventing more unrealistic pickup promises.",
      confidence: 89,
      assumptions: ["Food Court B inventory remains available", "Pickup ETA changes publish immediately", "One cashier can move without ride coverage loss"],
      projectedMetrics: [
        { label: "Open backlog", before: "143", after: "96", tone: "ok" },
        { label: "Pickup ETA", before: "34m", after: "24m", tone: "ok" },
        { label: "Revenue loss", before: "MED", after: "LOW", tone: "ok" },
      ],
    },
    smartActions: [
      { channel: "guest_app", target: "Guests within 300m", payload: "Food Court B pizza combo is faster now. Food Court A pickup ETA is 30-35 minutes.", guardrail: "Only promote inventory confirmed in stock." },
      { channel: "digital_signage", target: "Food Court A menu boards", payload: "Temporarily hide constrained items and show updated ETA.", guardrail: "Do not accept orders with unavailable SKUs." },
      { channel: "worker_device", target: "Snack Stand C cashier", payload: "Move to Food Court A pickup staging for 20 minutes.", guardrail: "Time-boxed move; no kitchen lead removal." },
    ],
    guestSegments: [
      { segment: "Mobile-order guests", trigger: "Pickup ETA exceeds 30m", message: "Food Court B has faster pickup and available combo inventory.", incentive: "Small app-only combo upgrade", privacy: "Order state aggregated by kitchen queue." },
      { segment: "Nearby families", trigger: "Within Adventure Zone lunch cluster", message: "Shorter food line nearby at Food Court B.", privacy: "Coarse location radius only." },
    ],
    dataReadiness: [
      { source: "Inventory", status: "ready", latency: "12s", coverage: "94%", impact: "Prevents hallucinated menu recommendations." },
      { source: "Mobile orders", status: "ready", latency: "real time", coverage: "100%", impact: "Safe to correct pickup ETA." },
      { source: "Kitchen labor", status: "watch", latency: "4m", coverage: "74%", impact: "Requires staff confirmation after cashier move." },
    ],
  },
  storm_response: {
    connectedData: [
      { source: "Weather nowcast", signal: "72% storm risk and outdoor queue exposure", status: "live" },
      { source: "Indoor density sensors", signal: "Shelter zones absorbing guests", status: "live" },
      { source: "BMS energy feed", signal: "Grid load at 93% peak pressure", status: "live" },
      { source: "Digital signage CMS", signal: "Covered-route signs ready", status: "watch" },
    ],
    digitalTwin: {
      horizon: "Next 25 minutes",
      prediction: "Splitting shelter routing and protecting HVAC avoids one indoor bottleneck while still reducing noncritical energy load.",
      confidence: 84,
      assumptions: ["Storm window continues rising", "Outdoor queue taper starts within 10m", "BMS accepts shelter-zone HVAC lock"],
      projectedMetrics: [
        { label: "Outdoor exposure", before: "HIGH", after: "LOW", tone: "ok" },
        { label: "Shelter comfort", before: "71", after: "82", tone: "ok" },
        { label: "Grid load", before: "93%", after: "88%", tone: "watch" },
      ],
    },
    smartActions: [
      { channel: "guest_app", target: "Outdoor queue guests", payload: "Storm routing active. Use Theater B, Indoor Launch, Arcade, and covered paths.", guardrail: "Do not imply outdoor rides remain safe." },
      { channel: "equipment_controller", target: "Building management system", payload: "Protect HVAC setpoints in active shelter zones; shed noncritical lighting.", guardrail: "Comfort in shelter zones overrides energy savings." },
      { channel: "digital_signage", target: "Outdoor-to-indoor paths", payload: "Covered route arrows to Theater B, Arcade, and Indoor Launch.", guardrail: "Split demand across multiple indoor zones." },
    ],
    guestSegments: [
      { segment: "Outdoor queue guests", trigger: "Storm risk above routing threshold", message: "Move to covered routes now; indoor options are open nearby.", privacy: "Zone-level exposure signal only." },
      { segment: "Accessibility-priority guests", trigger: "Covered route needed", message: "Accessible covered path to Theater B and First Aid remains open.", privacy: "No medical or disability status exposed." },
    ],
    dataReadiness: [
      { source: "Weather", status: "ready", latency: "30s", coverage: "100%", impact: "Safe to taper outdoor queues." },
      { source: "Indoor density", status: "ready", latency: "18s", coverage: "88%", impact: "Supports multi-shelter routing." },
      { source: "BMS feedback", status: "watch", latency: "90s", coverage: "71%", impact: "Needs confirmation that HVAC command applied." },
    ],
  },
};

export const DEMO_SCENARIOS: Record<ScenarioKey, DemoScenario> = {
  ride_down: {
    key: "ride_down",
    label: "Scenario A",
    title: "Ride Down",
    situation: "Dragon Coaster is down with a 44-minute current estimate. 540 guests are still nearby after intake pause, Indoor Ride B already has a 55-minute wait, and Food Court 2 is understaffed.",
    riskLevel: "HIGH",
    confidence: 0.82,
    humanApproval: true,
    metrics: [
      { label: "Ride outage", value: "44m", detail: "Dragon Coaster maintenance hold.", tone: "risk" },
      { label: "Guests nearby", value: "540", detail: "Crowd still clustered in Dragon Zone.", tone: "risk" },
      { label: "Alt ride wait", value: "55m", detail: "Indoor Ride B is already overloaded.", tone: "risk" },
      { label: "Staff gap", value: "2", detail: "Crowd-control staff needed nearby.", tone: "watch" },
      { label: "Comp cost", value: "$", detail: "Use targeted recovery, not blanket vouchers.", tone: "watch" },
    ],
    actions: [
      {
        action: "Pause new queue intake at Dragon Coaster and mark the existing queue as maintenance-hold.",
        owner: "Ride Ops",
        deadline: "5m",
        expectedImpact: "Prevents 300 additional guests from joining a dead queue.",
      },
      {
        action: "Redirect thrill-seekers to Sky Drop and Indoor Launch, but cap Indoor Ride B promotion.",
        owner: "Guest Flow",
        deadline: "10m",
        expectedImpact: "Reduces Dragon Zone density by 18% without creating a new indoor bottleneck.",
      },
      {
        action: "Move two crowd-control staff to Dragon Zone and one greeter to Indoor Launch.",
        owner: "Staffing",
        deadline: "10m",
        expectedImpact: "Keeps exit flow calm and protects ride operators from guest-service overload.",
      },
      {
        action: "Send a guest app message with honest downtime, nearby alternatives, and limited recovery offer.",
        owner: "Guest Experience",
        deadline: "8m",
        expectedImpact: "Improves recovery satisfaction without over-promising reopening time.",
      },
    ],
    tradeoffs: [
      { label: "Guest satisfaction", value: "Short-term frustration, better recovery if messaging is immediate." },
      { label: "Staff stress", value: "Adds crowd-control demand, but protects ride operators." },
      { label: "Revenue", value: "Targeted recovery offer instead of blanket compensation." },
      { label: "Safety", value: "Maintenance hold remains non-negotiable." },
    ],
    policies: [
      { area: "Safety", rule: "No reopening, test dispatch, or queue expansion until maintenance clearance is recorded.", enforcement: "Blocks any action that reduces the Dragon Coaster hold." },
      { area: "Operations", rule: "Redistribute demand only to zones with verified capacity and trained staff coverage.", enforcement: "Caps Indoor Launch promotion while Sky Drop, shows, and food absorb demand." },
      { area: "Experience", rule: "Give guests an honest downtime estimate and useful alternatives within walking distance.", enforcement: "Requires app and sign messaging before broad rerouting." },
      { area: "Customer Care", rule: "Offer recovery support proportionate to guest impact without blanket compensation.", enforcement: "Targets affected queue guests and logs sentiment after delivery." },
    ],
    evals: [
      { label: "Groundedness", score: 91, detail: "Uses actual ride status, queue size, and alternate wait data." },
      { label: "Capacity awareness", score: 88, detail: "Avoids dumping all guests into already-overloaded Indoor Ride B." },
      { label: "Staff impact", score: 76, detail: "Adds staff where needed but creates a near-term coverage gap." },
      { label: "Guest recovery", score: 84, detail: "Message is helpful and honest about downtime uncertainty." },
      { label: "Safety", score: 96, detail: "Does not suggest shortcutting maintenance or reopening without clearance." },
      { label: "Actionability", score: 89, detail: "Owners, deadlines, and expected impacts are specific." },
      { label: "Take rate", score: 34, detail: "Measures whether the guest offer actually redirects guests from the down ride." },
      { label: "Positive response", score: 78, detail: "Tracks guest sentiment and worker acknowledgment after delivery." },
      { label: "Reactive follow-through", score: 29, detail: "Checks whether guests and staff physically move toward recommended zones." },
    ],
    eyEvals: EY_EVALS,
    experienceModel: EY_EXPERIENCE_MODELS.ride_down,
    agentBriefs: [
      { name: "Ride Ops Agent", signal: "Dragon Coaster down", finding: "Keep the ride in maintenance hold and stop new queue intake immediately.", tone: "risk" },
      { name: "Guest Flow Agent", signal: "540 guests nearby", finding: "Split guests across Sky Drop, Indoor Launch, shows, and food instead of one ride.", tone: "risk" },
      { name: "Staffing Agent", signal: "2 staff needed", finding: "Shift crowd-control staff without pulling trained ride operators below minimums.", tone: "watch" },
      { name: "Food Agent", signal: "Food Court 2 low staff", finding: "Do not route the whole crowd through Food Court 2 during the outage.", tone: "watch" },
      { name: "GCP Eval Judge", signal: "96 safety", finding: "Flags any recommendation that implies reopening before maintenance clearance.", tone: "ok" },
    ],
    mongoFocus: [
      ["rides", "Dragon Coaster status, downtime estimate, capacity, staffing minimums"],
      ["park_state", "nearby guest density, alternate ride waits, food court pressure"],
      ["playbooks", "past ride-breakdown crowd redistribution procedures"],
      ["agent_decisions", "final plan, tradeoffs, confidence, and human approval flag"],
    ],
    runMessage: "Decision Bridge applied Ride Down response: paused queue intake, split guest routing, protected maintenance safety, and logged the plan for GCP internal evaluation.",
  },
  staff_shortage: {
    key: "staff_shortage",
    label: "Scenario B",
    title: "Staff Shortage",
    situation: "Multiple workers call out during peak demand. Ride waits are rising, food lines are long, and protected break windows are at risk.",
    riskLevel: "HIGH",
    confidence: 0.78,
    humanApproval: true,
    metrics: [
      { label: "Callouts", value: "18", detail: "Open roles across rides, food, and guest flow.", tone: "risk" },
      { label: "Break risk", value: "HIGH", detail: "Two teams are near protected break windows.", tone: "risk" },
      { label: "Ride waits", value: "+24m", detail: "Dispatch frequency is slipping.", tone: "watch" },
      { label: "Food wait", value: "38m", detail: "Mobile pickup and cashier queues are rising.", tone: "risk" },
      { label: "Labor cost", value: "$$", detail: "Use targeted overtime only where it unlocks capacity.", tone: "watch" },
    ],
    actions: [
      {
        action: "Protect scheduled breaks for safety-critical operators and rotate supervisors into guest-facing queues.",
        owner: "Staffing",
        deadline: "5m",
        expectedImpact: "Reduces fatigue risk without violating minimum staffing.",
      },
      {
        action: "Reduce dispatch frequency on two lower-demand rides instead of keeping every ride at peak throughput.",
        owner: "Ride Ops",
        deadline: "12m",
        expectedImpact: "Frees trained staff while limiting guest impact to lower-demand areas.",
      },
      {
        action: "Close Snack Stand C temporarily and move one cashier to Food Court 1.",
        owner: "Food Ops",
        deadline: "10m",
        expectedImpact: "Cuts the highest food wait while preserving core meal capacity.",
      },
      {
        action: "Send internal alert: no break delays beyond policy threshold without manager approval.",
        owner: "Decision Bridge",
        deadline: "Now",
        expectedImpact: "Makes worker wellbeing a hard constraint, not a soft preference.",
      },
    ],
    tradeoffs: [
      { label: "Guest satisfaction", value: "Some lower-priority rides slow down to prevent broader service collapse." },
      { label: "Worker wellbeing", value: "Break windows are protected even when queues are rising." },
      { label: "Cost", value: "Targeted overtime is allowed only where it unlocks high-demand capacity." },
      { label: "Safety", value: "Trained-operator minimums override throughput pressure." },
    ],
    policies: [
      { area: "Safety", rule: "Certified operator minimums and fatigue limits cannot be bypassed to protect throughput.", enforcement: "Flags any plan that pulls trained operators below required coverage." },
      { area: "Operations", rule: "Redeployment must match training tags, location needs, and break-window constraints.", enforcement: "Routes only cross-trained staff and time-boxes temporary moves." },
      { area: "Experience", rule: "Slow lower-demand attractions before allowing system-wide queue collapse.", enforcement: "Prioritizes the highest guest-impact rides and food locations." },
      { area: "Customer Care", rule: "Staff messages must be specific, respectful, and acknowledge protected breaks.", enforcement: "Requires clear owner, destination, and duration for each redeployment." },
    ],
    evals: [
      { label: "Groundedness", score: 89, detail: "Uses staffing, wait, and break-window data." },
      { label: "Staff stress", score: 93, detail: "Protects breaks and avoids unlimited redeployment." },
      { label: "Operational feasibility", score: 81, detail: "Moves staff across compatible roles only." },
      { label: "Guest impact", score: 77, detail: "Accepts localized wait increases to reduce system-wide risk." },
      { label: "Policy compliance", score: 95, detail: "Flags break-delay policy as a hard guardrail." },
      { label: "Conflict resolution", score: 86, detail: "Balances ride ops, food ops, and worker wellbeing." },
      { label: "Take rate", score: 96, detail: "Measures whether assigned staff acknowledge and accept redeployment." },
      { label: "Positive response", score: 88, detail: "Tracks whether staff response is timely and non-escalatory." },
      { label: "Reactive follow-through", score: 91, detail: "Checks whether staff actually move toward the crowded zone." },
    ],
    eyEvals: EY_EVALS,
    experienceModel: EY_EXPERIENCE_MODELS.staff_shortage,
    agentBriefs: [
      { name: "Staffing Agent", signal: "18 callouts", finding: "Protect breaks and redeploy only cross-trained staff.", tone: "risk" },
      { name: "Ride Ops Agent", signal: "+24m waits", finding: "Reduce dispatch on lower-demand rides before cutting high-demand capacity.", tone: "watch" },
      { name: "Food Agent", signal: "38m food wait", finding: "Close one low-volume stand and move cashier capacity to Food Court 1.", tone: "risk" },
      { name: "Energy Agent", signal: "neutral", finding: "No energy action should create additional indoor comfort risk.", tone: "ok" },
      { name: "GCP Eval Judge", signal: "93 staff", finding: "Catches plans that solve guest waits by abusing worker breaks.", tone: "ok" },
    ],
    mongoFocus: [
      ["staff_shifts", "availability, training tags, break windows, fatigue and stress scores"],
      ["park_state", "ride wait times, food queues, zone density, active policies"],
      ["agent_decisions", "redeployment plan and rejected alternatives"],
      ["eval_results", "staff-stress, policy, and conflict-resolution scores"],
    ],
    runMessage: "Decision Bridge applied Staff Shortage response: protected breaks, redeployed cross-trained staff, and sent the plan to GCP internal eval for worker-stress evaluation.",
  },
  food_spike: {
    key: "food_spike",
    label: "Scenario C",
    title: "Food Demand Spike",
    situation: "Lunch demand spikes near Adventure Zone. Mobile orders are backing up, chicken tenders and bottled drinks are low, and Food Court B has spare capacity.",
    riskLevel: "MEDIUM",
    confidence: 0.86,
    humanApproval: false,
    metrics: [
      { label: "Mobile backlog", value: "143", detail: "Open orders waiting in Food Court A.", tone: "risk" },
      { label: "Low stock", value: "2 SKUs", detail: "Chicken tenders and bottled drinks are constrained.", tone: "risk" },
      { label: "Pickup ETA", value: "34m", detail: "Current app promise is no longer realistic.", tone: "risk" },
      { label: "Nearby capacity", value: "42%", detail: "Food Court B has available kitchen load.", tone: "ok" },
      { label: "Revenue risk", value: "MED", detail: "Redirect demand instead of shutting ordering off.", tone: "watch" },
    ],
    actions: [
      {
        action: "Temporarily hide chicken tenders and bottled drinks from Mobile Order at Food Court A.",
        owner: "Food Ops",
        deadline: "3m",
        expectedImpact: "Stops guests from ordering items that cannot be fulfilled reliably.",
      },
      {
        action: "Promote pizza combo and fountain drinks at Food Court B for guests within 300 meters.",
        owner: "Guest Messaging",
        deadline: "5m",
        expectedImpact: "Shifts demand to available inventory while preserving sales.",
      },
      {
        action: "Move one cashier from Snack Stand C to Food Court A pickup staging.",
        owner: "Staffing",
        deadline: "8m",
        expectedImpact: "Reduces pickup queue friction without starving ride operations.",
      },
      {
        action: "Update pickup estimates from 18 minutes to 30-35 minutes until backlog clears.",
        owner: "Food Ops",
        deadline: "Now",
        expectedImpact: "Prevents misleading guest promises and lowers complaint risk.",
      },
    ],
    tradeoffs: [
      { label: "Guest satisfaction", value: "Fewer menu choices, but more honest pickup times." },
      { label: "Revenue", value: "Preserves sales by redirecting demand to in-stock items." },
      { label: "Staff stress", value: "Adds one cashier to pickup staging without pulling kitchen leads." },
      { label: "Fairness", value: "Avoids over-promising scarce inventory to late-arriving guests." },
    ],
    policies: [
      { area: "Safety", rule: "Food availability and prep-time promises must match live inventory and kitchen load.", enforcement: "Suppresses low-stock SKUs before accepting new orders." },
      { area: "Operations", rule: "Move demand toward kitchens with spare load before shutting off ordering.", enforcement: "Promotes Food Court B only inside the affected guest radius." },
      { area: "Experience", rule: "Pickup ETAs must be corrected before guests commit to delayed orders.", enforcement: "Updates app estimates when backlog exceeds service threshold." },
      { area: "Customer Care", rule: "Guests with constrained orders need proactive substitutions or refunds.", enforcement: "Creates targeted recovery messages for affected mobile orders." },
    ],
    evals: [
      { label: "Inventory groundedness", score: 94, detail: "Recommendations match SKU availability and kitchen load." },
      { label: "Demand logic", score: 90, detail: "Responds to order backlog and local guest density." },
      { label: "Guest fairness", score: 87, detail: "Pickup estimates are corrected before new orders arrive." },
      { label: "Revenue impact", score: 84, detail: "Redirects demand instead of turning mobile ordering off." },
      { label: "Staff impact", score: 79, detail: "Staff move is useful but should be time-boxed." },
      { label: "Actionability", score: 92, detail: "Specific menu, location, staffing, and ETA changes." },
      { label: "Take rate", score: 28, detail: "Measures whether guests accept the Food Court B redirect offer." },
      { label: "Positive response", score: 73, detail: "Tracks guest response to item suppression and pickup-time changes." },
      { label: "Reactive follow-through", score: 24, detail: "Checks whether demand shifts away from the overloaded kitchen." },
    ],
    eyEvals: EY_EVALS,
    experienceModel: EY_EXPERIENCE_MODELS.food_spike,
    agentBriefs: [
      { name: "Food Agent", signal: "143 order backlog", finding: "Suppress constrained SKUs and promote Food Court B inventory.", tone: "risk" },
      { name: "Inventory Agent", signal: "2 low-stock SKUs", finding: "Do not recommend items MongoDB inventory marks below threshold.", tone: "risk" },
      { name: "Guest Flow Agent", signal: "300m radius", finding: "Target the offer only to nearby guests to avoid creating a new rush.", tone: "watch" },
      { name: "Staffing Agent", signal: "1 cashier move", finding: "Move a cashier temporarily, not a kitchen lead.", tone: "watch" },
      { name: "GCP Eval Judge", signal: "94 grounded", finding: "Catches hallucinated menu items and unrealistic pickup promises.", tone: "ok" },
    ],
    mongoFocus: [
      ["food_inventory", "SKU inventory, kitchen load, prep times, restock signals"],
      ["guest_messages", "targeted app notifications and offer copy"],
      ["park_state", "restaurant queue, guest density, and nearby capacity"],
      ["eval_results", "inventory groundedness, fairness, revenue, and actionability scores"],
    ],
    runMessage: "Decision Bridge applied Food Demand Spike response: suppressed low-stock items, shifted demand to Food Court B, updated pickup ETAs, and logged inventory-grounded evals.",
  },
  storm_response: {
    key: "storm_response",
    label: "Scenario D",
    title: "Storm + HVAC Pressure",
    situation: "Storm risk and indoor shelter demand rise together while grid cost peaks. Outdoor queues must taper without sacrificing indoor comfort.",
    riskLevel: "HIGH",
    confidence: 0.8,
    humanApproval: false,
    metrics: [
      { label: "Storm risk", value: "72%", detail: "Outdoor queues likely need staged closure.", tone: "risk" },
      { label: "Indoor load", value: "HIGH", detail: "Shelter zones will absorb demand.", tone: "risk" },
      { label: "Grid load", value: "93%", detail: "Energy cost is peaking.", tone: "watch" },
      { label: "HVAC", value: "Protect", detail: "Comfort setpoints should not be shed in shelter areas.", tone: "risk" },
      { label: "Guest flow", value: "Split", detail: "Avoid creating one indoor bottleneck.", tone: "watch" },
    ],
    actions: [
      {
        action: "Taper outdoor queue intake and redirect guests into multiple covered and indoor zones.",
        owner: "Ride Ops",
        deadline: "10m",
        expectedImpact: "Reduces exposed guests before the weather window.",
      },
      {
        action: "Protect HVAC setpoints in Indoor Hub, Arcade Zone, and Covered Plaza.",
        owner: "Facilities",
        deadline: "Now",
        expectedImpact: "Keeps shelter zones usable while other noncritical loads are reduced.",
      },
      {
        action: "Send app guidance for indoor shows, arcade capacity, and covered paths.",
        owner: "Guest Messaging",
        deadline: "5m",
        expectedImpact: "Moves guests without implying outdoor rides are safe to queue for.",
      },
    ],
    tradeoffs: [
      { label: "Safety", value: "Outdoor exposure and queue safety override throughput." },
      { label: "Guest satisfaction", value: "Indoor comfort is protected despite energy pressure." },
      { label: "Energy cost", value: "Shed only noncritical loads while shelter demand is high." },
      { label: "Staff stress", value: "Crowd-control work shifts to covered paths and indoor doors." },
    ],
    policies: [
      { area: "Safety", rule: "Outdoor exposure risk overrides ride throughput, energy cost, and recovery offers.", enforcement: "Tapers outdoor queues before the storm window reaches closure threshold." },
      { area: "Operations", rule: "Shelter routing must split demand across multiple covered and indoor zones.", enforcement: "Prevents sending all guests to one indoor hub or path junction." },
      { area: "Experience", rule: "Comfort systems in active shelter zones are protected during weather events.", enforcement: "Allows only noncritical lighting and back-of-house load reduction." },
      { area: "Customer Care", rule: "Weather guidance must be calm, clear, and avoid implying outdoor rides remain safe.", enforcement: "Requires app copy with covered routes, indoor options, and service updates." },
    ],
    evals: [
      { label: "Groundedness", score: 90, detail: "Uses storm risk, indoor density, and grid load." },
      { label: "Safety", score: 96, detail: "Avoids keeping outdoor queues exposed." },
      { label: "Energy balance", score: 84, detail: "Protects HVAC where guests are sheltering." },
      { label: "Capacity awareness", score: 82, detail: "Splits guests across multiple indoor locations." },
      { label: "Take rate", score: 42, detail: "Measures whether guests accept the shelter-route guidance." },
      { label: "Positive response", score: 81, detail: "Tracks guest sentiment and BMS command acceptance." },
      { label: "Reactive follow-through", score: 35, detail: "Checks whether guests move indoors and HVAC settings apply." },
    ],
    eyEvals: EY_EVALS,
    experienceModel: EY_EXPERIENCE_MODELS.storm_response,
    agentBriefs: [
      { name: "Weather Agent", signal: "storm window", finding: "Taper outdoor queues before closure pressure becomes unsafe.", tone: "risk" },
      { name: "Guest Flow Agent", signal: "shelter load", finding: "Split shelter demand across indoor rides, arcade, theater, and covered paths.", tone: "risk" },
      { name: "Energy Agent", signal: "peak price", finding: "Preserve HVAC in shelter zones and shed lower-impact loads only.", tone: "watch" },
      { name: "Staffing Agent", signal: "path control", finding: "Move crowd-control staff to covered path junctions.", tone: "watch" },
      { name: "GCP Eval Judge", signal: "safety first", finding: "Flags plans that optimize energy cost over guest comfort and weather risk.", tone: "ok" },
    ],
    mongoFocus: [
      ["park_state", "weather risk, indoor density, outdoor queue pressure, and energy load"],
      ["playbooks", "storm queue taper and shelter-routing procedures"],
      ["guest_messages", "storm-safe app guidance and attraction recommendations"],
      ["eval_results", "safety, comfort, energy balance, and response take-rate scores"],
    ],
    runMessage: "Decision Bridge applied Storm Response: tapered outdoor queues, protected shelter-zone HVAC, routed guests indoors, and logged response evals.",
  },
};

export const DEFAULT_EVENT_PROMPT =
  "Deploy an evening event for 8,000 guests from 6 PM to midnight. Include themed experiences, food pop-ups, merchandise, lighting, barriers, extra staff, and clear guest routing. Do not block the main parade route.";

export const DEFAULT_EVENT_THEME = "Seasonal night market";

export function formatTime(hour: number, minute: number) {
  const normalizedHour = hour % 24;
  const ampm = normalizedHour >= 12 ? "PM" : "AM";
  const displayHour = normalizedHour % 12 || 12;
  return `${displayHour}:${String(minute).padStart(2, "0")} ${ampm}`;
}

export function pct(value: number) {
  return `${Math.round(value)}%`;
}

export function toneClass(tone: "risk" | "watch" | "ok") {
  if (tone === "risk") return "border-red-500/40 bg-red-950/20 text-red-100";
  if (tone === "watch") return "border-amber-500/40 bg-amber-950/20 text-amber-100";
  return "border-emerald-500/40 bg-emerald-950/20 text-emerald-100";
}

export function policyClass(area: PolicyArea) {
  if (area === "Safety") return "border-red-500/40 bg-red-950/20 text-red-100";
  if (area === "Operations") return "border-cyan-500/40 bg-cyan-950/20 text-cyan-100";
  if (area === "Experience") return "border-emerald-500/40 bg-emerald-950/20 text-emerald-100";
  return "border-violet-500/40 bg-violet-950/20 text-violet-100";
}

export function toneFill(tone: "risk" | "watch" | "ok") {
  if (tone === "risk") return "bg-red-500";
  if (tone === "watch") return "bg-amber-400";
  return "bg-emerald-400";
}

export function pressureTone(value: number): "risk" | "watch" | "ok" {
  if (value >= 80) return "risk";
  if (value >= 60) return "watch";
  return "ok";
}

export function ratePct(value?: number) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

export function dispatchLabel(channel?: string) {
  if (channel === "guest_app") return "Guest app";
  if (channel === "worker_device") return "Worker device";
  if (channel === "equipment_controller") return "Equipment";
  return channel ?? "Dispatch";
}

export function dispatchBody(dispatch: DeliveryDispatch) {
  const payload = dispatch.payload ?? {};
  if (payload.message) return payload.message;
  if (payload.task) return payload.task;
  if (payload.command) return `${payload.command}${payload.zones?.length ? ` / ${payload.zones.join(", ")}` : ""}`;
  return payload.promotion?.offer ?? "Operational action emitted.";
}

export function dispatchTone(channel?: string) {
  if (channel === "guest_app") return "border-cyan-400/40 bg-cyan-950/20 text-cyan-100";
  if (channel === "worker_device") return "border-amber-400/40 bg-amber-950/20 text-amber-100";
  if (channel === "equipment_controller") return "border-emerald-400/40 bg-emerald-950/20 text-emerald-100";
  return "border-slate-700 bg-slate-950 text-slate-200";
}
