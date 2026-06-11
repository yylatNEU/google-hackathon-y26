export class ParkPulseAHPClient {
  constructor({ apiBase, fetchImpl } = {}) {
    this.apiBase = (apiBase || "http://127.0.0.1:8000").replace(/\/$/, "");
    this.fetch = fetchImpl || globalThis.fetch;
    if (!this.fetch) throw new Error("ParkPulseAHPClient requires fetch.");
  }

  async request(path, body) {
    const response = await this.fetch(`${this.apiBase}${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || payload.reason || `HTTP ${response.status}`);
    return payload;
  }

  docs() {
    return this.request("/api/park/agent-handshake/docs");
  }

  liveState(scenarioMode) {
    return this.request("/api/park/agent-handshake/live-state", { scenario_mode: scenarioMode });
  }

  consentGrant({ subject, agentId, scope, cannotDo, scenarioMode }) {
    return this.request("/api/park/agent-handshake/consent-grant", {
      subject,
      agent_id: agentId,
      scope,
      cannot_do: cannotDo,
      scenario_mode: scenarioMode,
    });
  }

  delegationToken({ subject, agentId, scope, cannotDo, ttlSeconds = 10800 }) {
    return this.request("/api/park/delegation-token", {
      subject,
      agent_id: agentId,
      scope,
      cannot_do: cannotDo,
      ttl_seconds: ttlSeconds,
    });
  }

  handshake(payload) {
    return this.request("/api/park/handshake", payload);
  }

  capabilities(sessionId, payload) {
    return this.request(`/api/park/session/${sessionId}/capabilities`, payload);
  }

  intent(sessionId, payload) {
    return this.request(`/api/park/session/${sessionId}/intent`, payload);
  }

  propose(sessionId, payload) {
    return this.request(`/api/park/session/${sessionId}/propose`, payload);
  }

  counter(sessionId, payload) {
    return this.request(`/api/park/session/${sessionId}/counter`, payload);
  }

  commit(sessionId, payload) {
    return this.request(`/api/park/session/${sessionId}/commit`, payload);
  }

  monitor(sessionId, payload) {
    return this.request(`/api/park/session/${sessionId}/monitor`, payload);
  }

  receipt(sessionId, payload) {
    return this.request(`/api/park/session/${sessionId}/receipt`, payload);
  }

  verifyArtifact(artifact, expectedArtifactType) {
    return this.request("/api/park/agent-handshake/verify-artifact", {
      artifact,
      expected_artifact_type: expectedArtifactType,
    });
  }

  externalClientDemo(payload) {
    return this.request("/api/park/agent-handshake/external-client-demo", payload);
  }
}

export default ParkPulseAHPClient;
