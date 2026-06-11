type Json = Record<string, unknown>;

const api = process.env.PARKPULSE_API_URL ?? "http://127.0.0.1:8000";

const fullScope = [
  "location",
  "party_size",
  "preferences",
  "accessibility_needs",
  "budget",
  "ride_preference",
  "route_plan",
  "wait_time_alert",
  "food_recommendation",
  "safety_notice",
  "compensation_offer",
  "policy_check",
  "session_commit",
];

async function post<T extends Json>(path: string, body: Json): Promise<T> {
  const response = await fetch(`${api}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as T;
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}: ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function get<T extends Json>(path: string): Promise<T> {
  const response = await fetch(`${api}${path}`, {
    method: "GET",
    headers: { "accept": "application/json" },
  });
  const payload = (await response.json()) as T;
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}: ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function run() {
  const agentId = `john_personal_agent_${Date.now()}`;
  const issuer = await get<{ signing?: { kid?: string } }>("/api/park/agent-onboarding/issuer");
  const registered = await post<{ agent: Json }>("/api/park/agent-onboarding/register", {
    agent_id: agentId,
    display_name: "John Personal Agent",
    partner_id: "john_family_os",
    partner_name: "John Family OS",
    requested_scopes: fullScope,
    cannot_do: ["auto_purchase", "share_health_data", "accept_refund_without_user"],
    use_case: "guest_route_planning",
  });
  const certified = await post<{ agent: Json; certification: { credential: Json } }>(`/api/park/agent-onboarding/${agentId}/certify`, {});
  const certificationCredential = certified.certification.credential;
  const certificationProof = await post<{ status: string; signature_status: string }>("/api/park/agent-onboarding/verify-credential", {
    credential: certificationCredential,
  });
  if (certificationCredential.kid !== issuer.signing?.kid) {
    throw new Error(`Certification kid mismatch: ${String(certificationCredential.kid)} vs ${String(issuer.signing?.kid)}`);
  }

  const issued = await post<{ token: Json }>("/api/park/delegation-token", {
    subject: "guest_user_123",
    agent_id: agentId,
    scope: fullScope,
    cannot_do: ["auto_purchase", "share_health_data", "accept_refund_without_user"],
    ttl_seconds: 10_800,
  });
  const delegation_token = issued.token;

  const identity = await post<{ session: { session_id: string }; case_evaluation: Json }>("/api/park/handshake", {
    agent_id: agentId,
    represents: "guest_user_123",
    proof: "signed_token",
    requested_session: `example_visit_${Date.now()}`,
    delegation_token,
  });
  const sessionId = identity.session.session_id;

  const scoped = await post<{ case_evaluation: Json }>(`/api/park/session/${sessionId}/capabilities`, {
    can_share: ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"],
    can_receive: ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"],
    cannot_do: ["auto_purchase", "share_health_data", "accept_refund_without_user"],
    delegation_token,
  });

  await post(`/api/park/session/${sessionId}/intent`, {
    goal: "maximize_family_satisfaction",
    time_window: "3_hours",
    constraints: {
      children: 2,
      avoid_wait_over_minutes: 35,
      avoid_thrill_rides: true,
      food_allergy: "peanut",
    },
    delegation_token,
  });

  const proposal = await post<{ proposal: { proposal_id: string; plan: string[]; expected_wait_saved: string } }>(`/api/park/session/${sessionId}/propose`, {
    planner: "live_state",
    horizon: "3_hours",
    delegation_token,
  });

  await post(`/api/park/session/${sessionId}/counter`, {
    counter_request: "reduce walking distance",
    priority_change: { walking_distance: "highest", wait_time: "medium" },
    delegation_token,
  });

  await post(`/api/park/session/${sessionId}/commit`, {
    accepted: true,
    notify_user: true,
    delegation_token,
  });

  const commerce = await post<{ status: string; case_evaluation: Json }>("/api/park/internal-agents/commerce/evaluate", {
    session_id: sessionId,
    action: "payment",
    amount: 42,
    reason: "Example client proves payment is gated.",
    delegation_token,
  });

  const queue = await post<{ status: string; case_evaluation: Json; proposal: { proposal_id: string } }>("/api/park/internal-agents/queue/reroute", {
    session_id: sessionId,
    walking_priority: "highest",
    reason: "Example client asks Queue Agent for a lower-walking route.",
    delegation_token,
  });

  console.log(
    JSON.stringify(
      {
        agent: {
          agent_id: agentId,
          registration: registered.agent,
          certification: certified.agent,
          certification_proof: certificationProof,
          issuer,
        },
        session_id: sessionId,
        proof: {
          identity: identity.case_evaluation,
          scope: scoped.case_evaluation,
          commerce: commerce.case_evaluation,
          queue: queue.case_evaluation,
        },
        first_plan: proposal.proposal,
        reroute_proposal_id: queue.proposal.proposal_id,
      },
      null,
      2,
    ),
  );
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
