package com.parkpulse.backend;

import java.util.Map;
import java.util.NoSuchElementException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class AgentHandshakeController {
    private final AgentHandshakeService agentHandshakeService;

    public AgentHandshakeController(AgentHandshakeService agentHandshakeService) {
        this.agentHandshakeService = agentHandshakeService;
    }

    @PostMapping(value = "/api/park/handshake", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> identityHandshake(@RequestBody(required = false) Map<String, Object> body) {
        return agentHandshakeService.identityHandshake(body == null ? Map.of() : body);
    }

    @GetMapping(value = "/api/park/session/{sessionId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> getSession(@PathVariable String sessionId) {
        try {
            return agentHandshakeService.getSession(sessionId);
        } catch (NoSuchElementException error) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, error.getMessage(), error);
        }
    }

    @PostMapping(value = "/api/park/session/{sessionId}/capabilities", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> capabilityHandshake(@PathVariable String sessionId, @RequestBody(required = false) Map<String, Object> body) {
        try {
            return agentHandshakeService.capabilityHandshake(sessionId, body == null ? Map.of() : body);
        } catch (NoSuchElementException error) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, error.getMessage(), error);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, error.getMessage(), error);
        }
    }

    @PostMapping(value = "/api/park/session/{sessionId}/intent", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> intentHandshake(@PathVariable String sessionId, @RequestBody(required = false) Map<String, Object> body) {
        try {
            return agentHandshakeService.intentHandshake(sessionId, body == null ? Map.of() : body);
        } catch (NoSuchElementException error) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, error.getMessage(), error);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, error.getMessage(), error);
        }
    }

    @PostMapping(value = "/api/park/session/{sessionId}/propose", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> proposePlan(@PathVariable String sessionId, @RequestBody(required = false) Map<String, Object> body) {
        try {
            return agentHandshakeService.proposePlan(sessionId, body == null ? Map.of() : body);
        } catch (NoSuchElementException error) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, error.getMessage(), error);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, error.getMessage(), error);
        }
    }

    @PostMapping(value = "/api/park/internal-agents/commerce/evaluate", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> commerceAgentEvaluate(@RequestBody(required = false) Map<String, Object> body) {
        try {
            return agentHandshakeService.commerceAgentEvaluate(body == null ? Map.of() : body);
        } catch (NoSuchElementException error) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, error.getMessage(), error);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, error.getMessage(), error);
        }
    }

    @PostMapping(value = "/api/park/internal-agents/queue/reroute", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> queueAgentReroute(@RequestBody(required = false) Map<String, Object> body) {
        try {
            return agentHandshakeService.queueAgentReroute(body == null ? Map.of() : body);
        } catch (NoSuchElementException error) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, error.getMessage(), error);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, error.getMessage(), error);
        }
    }

    @PostMapping(value = "/api/park/session/{sessionId}/counter", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> counterProposal(@PathVariable String sessionId, @RequestBody(required = false) Map<String, Object> body) {
        try {
            return agentHandshakeService.counterProposal(sessionId, body == null ? Map.of() : body);
        } catch (NoSuchElementException error) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, error.getMessage(), error);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, error.getMessage(), error);
        }
    }

    @PostMapping(value = "/api/park/session/{sessionId}/commit", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> commitPlan(@PathVariable String sessionId, @RequestBody(required = false) Map<String, Object> body) {
        try {
            return agentHandshakeService.commitPlan(sessionId, body == null ? Map.of() : body);
        } catch (NoSuchElementException error) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, error.getMessage(), error);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, error.getMessage(), error);
        }
    }

    @GetMapping(value = "/api/park/session/{sessionId}/monitor", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> monitorSession(@PathVariable String sessionId) {
        return monitorSession(sessionId, Map.of());
    }

    @PostMapping(value = "/api/park/session/{sessionId}/monitor", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> monitorSession(@PathVariable String sessionId, @RequestBody(required = false) Map<String, Object> body) {
        try {
            return agentHandshakeService.monitorSession(sessionId, body == null ? Map.of() : body);
        } catch (NoSuchElementException error) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, error.getMessage(), error);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, error.getMessage(), error);
        }
    }

    @GetMapping(value = "/api/park/session/{sessionId}/receipt", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> sessionProtocolReceipt(@PathVariable String sessionId) {
        return sessionProtocolReceipt(sessionId, Map.of());
    }

    @PostMapping(value = "/api/park/session/{sessionId}/receipt", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> sessionProtocolReceipt(@PathVariable String sessionId, @RequestBody(required = false) Map<String, Object> body) {
        try {
            return agentHandshakeService.sessionProtocolReceipt(sessionId, body == null ? Map.of() : body);
        } catch (NoSuchElementException error) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, error.getMessage(), error);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, error.getMessage(), error);
        }
    }
}
