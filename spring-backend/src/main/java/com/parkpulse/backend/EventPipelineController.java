package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@RestController
public class EventPipelineController {
    private final EventPipelineService eventPipelineService;
    private final RoleAuthService roleAuthService;

    public EventPipelineController(EventPipelineService eventPipelineService, RoleAuthService roleAuthService) {
        this.eventPipelineService = eventPipelineService;
        this.roleAuthService = roleAuthService;
    }

    @GetMapping(value = "/api/park/events/contract", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> eventContract(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        return eventPipelineService.contract();
    }

    @GetMapping(value = "/api/park/events/status", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> eventStatus(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        return eventPipelineService.status();
    }

    @GetMapping(value = "/api/park/events/ledger", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> eventLedger(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        return eventPipelineService.recent(intParam(request.getParameter("limit"), 20), request.getParameter("event_type"));
    }

    @PostMapping(value = "/api/park/events/receiver/guest-response", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> guestResponse(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        requireReceiverToken(request);
        return eventPipelineService.recordReceiverEvent("parkpulse.receiver.guest_response", body == null ? Map.of() : body);
    }

    @PostMapping(value = "/api/park/events/receiver/worker-acknowledgement", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> workerAcknowledgement(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        requireReceiverToken(request);
        return eventPipelineService.recordReceiverEvent("parkpulse.receiver.worker_acknowledgement", body == null ? Map.of() : body);
    }

    @PostMapping(value = "/api/park/events/receiver/equipment-result", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> equipmentResult(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        requireReceiverToken(request);
        return eventPipelineService.recordReceiverEvent("parkpulse.receiver.equipment_result", body == null ? Map.of() : body);
    }

    @PostMapping(value = "/api/park/events/eventarc/park-signal", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> eventarcSignal(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        requireReceiverToken(request);
        return eventPipelineService.recordEventarcSignal(body == null ? Map.of() : body);
    }

    private void requireReceiverToken(HttpServletRequest request) {
        String token = request.getHeader("x-parkpulse-receiver-token");
        if (!eventPipelineService.receiverAuthorized(token)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Receiver event token is required.");
        }
    }

    private static int intParam(String raw, int defaultValue) {
        try {
            return Math.max(1, Math.min(100, Integer.parseInt(raw == null || raw.isBlank() ? String.valueOf(defaultValue) : raw)));
        } catch (NumberFormatException error) {
            return defaultValue;
        }
    }
}
