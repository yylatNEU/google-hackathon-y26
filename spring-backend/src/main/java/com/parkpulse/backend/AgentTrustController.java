package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AgentTrustController {
    private final AgentTrustService agentTrustService;
    private final RoleAuthService roleAuthService;
    private final RoleContractService roleContractService;

    public AgentTrustController(AgentTrustService agentTrustService, RoleAuthService roleAuthService, RoleContractService roleContractService) {
        this.agentTrustService = agentTrustService;
        this.roleAuthService = roleAuthService;
        this.roleContractService = roleContractService;
    }

    @GetMapping(value = "/api/park/agent-trust/status", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> agentTrustStatus(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "manage_agent_trust");
        Map<String, Object> payload = agentTrustService.status();
        payload.put("auth_boundary", roleContractService.identityReadiness());
        return payload;
    }

    @GetMapping(value = "/api/park/agent-trust/partners", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> agentTrustPartners(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "manage_agent_trust");
        return agentTrustService.partners();
    }

    @PostMapping(value = "/api/park/agent-trust/partners", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> upsertAgentTrustPartner(
        HttpServletRequest request,
        @RequestBody(required = false) Map<String, Object> body
    ) {
        roleAuthService.requireCapability(request, "manage_agent_trust");
        return agentTrustService.upsertPartner(body == null ? Map.of() : body);
    }

    @GetMapping(value = "/api/park/agent-trust/keys", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> agentTrustKeys(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "manage_agent_trust");
        return agentTrustService.keys();
    }

    @PostMapping(value = "/api/park/agent-trust/keys/rotate", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> rotateAgentTrustKey(
        HttpServletRequest request,
        @RequestBody(required = false) Map<String, Object> body
    ) {
        roleAuthService.requireCapability(request, "manage_agent_trust");
        return agentTrustService.rotateKey(body == null ? Map.of() : body);
    }

    @GetMapping(value = "/api/park/agent-trust/revocations", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> agentTrustRevocations(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "manage_agent_trust");
        return agentTrustService.revocations(intParam(request.getParameter("limit"), 100));
    }

    @GetMapping(value = "/api/park/agent-trust/audit", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> agentTrustAudit(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "manage_agent_trust");
        return agentTrustService.audit(intParam(request.getParameter("limit"), 100));
    }

    private static int intParam(String raw, int defaultValue) {
        try {
            return Math.max(1, Math.min(500, Integer.parseInt(raw == null || raw.isBlank() ? String.valueOf(defaultValue) : raw)));
        } catch (NumberFormatException error) {
            return defaultValue;
        }
    }
}
