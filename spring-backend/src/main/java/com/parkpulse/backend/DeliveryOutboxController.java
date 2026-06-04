package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class DeliveryOutboxController {
    private final DeliveryOutboxService deliveryOutboxService;
    private final DeliveryGcpAdapterService deliveryGcpAdapterService;
    private final DeliveryPartnerRetryService deliveryPartnerRetryService;
    private final RoleAuthService roleAuthService;

    public DeliveryOutboxController(DeliveryOutboxService deliveryOutboxService, DeliveryGcpAdapterService deliveryGcpAdapterService, DeliveryPartnerRetryService deliveryPartnerRetryService, RoleAuthService roleAuthService) {
        this.deliveryOutboxService = deliveryOutboxService;
        this.deliveryGcpAdapterService = deliveryGcpAdapterService;
        this.deliveryPartnerRetryService = deliveryPartnerRetryService;
        this.roleAuthService = roleAuthService;
    }

    @GetMapping(value = "/api/park/delivery/contract", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> deliveryContract(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        return deliveryOutboxService.contract();
    }

    @GetMapping(value = "/api/park/delivery/outbox", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> deliveryOutbox(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        return deliveryOutboxService.outbox(intParam(request.getParameter("limit"), 20));
    }

    @GetMapping(value = "/api/park/delivery/gcp-adapters/status", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> gcpAdapterStatus(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        return deliveryGcpAdapterService.status();
    }

    @GetMapping(value = "/api/park/delivery/partner-retries/status", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> partnerRetryStatus(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        return deliveryPartnerRetryService.status();
    }

    @PostMapping(value = "/api/park/delivery/partner-retries/run", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> runPartnerRetries(
        HttpServletRequest request,
        @RequestBody(required = false) Map<String, Object> body
    ) {
        roleAuthService.requireCapability(request, "dispatch_live_action");
        return deliveryPartnerRetryService.run(body == null ? Map.of() : body);
    }

    @PostMapping(value = "/api/park/delivery/guest-promotion", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> guestPromotion(
        HttpServletRequest request,
        @RequestBody(required = false) Map<String, Object> body
    ) {
        roleAuthService.requireCapability(request, "dispatch_live_action");
        return deliveryOutboxService.guestPromotion(body == null ? Map.of() : body);
    }

    @PostMapping(value = "/api/park/delivery/worker-notification", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> workerNotification(
        HttpServletRequest request,
        @RequestBody(required = false) Map<String, Object> body
    ) {
        roleAuthService.requireCapability(request, "dispatch_live_action");
        return deliveryOutboxService.workerNotification(body == null ? Map.of() : body);
    }

    @PostMapping(value = "/api/park/delivery/equipment-command", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> equipmentCommand(
        HttpServletRequest request,
        @RequestBody(required = false) Map<String, Object> body
    ) {
        roleAuthService.requireCapability(request, "dispatch_live_action");
        return deliveryOutboxService.equipmentCommand(body == null ? Map.of() : body);
    }

    @PostMapping(value = "/api/park/delivery/acknowledge", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> acknowledgeDelivery(
        HttpServletRequest request,
        @RequestBody(required = false) Map<String, Object> body
    ) {
        roleAuthService.requireCapability(request, "acknowledge_dispatch");
        Map<String, Object> payload = body == null ? Map.of() : body;
        return deliveryOutboxService.acknowledge(
            string(payload.get("dispatch_id"), payload.get("dispatchId")),
            stringOrDefault(payload.get("actor"), "operator"),
            stringOrDefault(payload.get("choice"), "acknowledged"),
            string(payload.get("channel"))
        );
    }

    @PostMapping(value = "/api/park/delivery/approval-decision", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> approvalDecision(
        HttpServletRequest request,
        @RequestBody(required = false) Map<String, Object> body
    ) {
        roleAuthService.requireCapability(request, "dispatch_live_action");
        Map<String, Object> payload = body == null ? Map.of() : body;
        return deliveryOutboxService.approvalDecision(
            string(payload.get("dispatch_id"), payload.get("dispatchId")),
            stringOrDefault(payload.get("actor"), "operator"),
            stringOrDefault(payload.get("decision"), "approved"),
            string(payload.get("reason")),
            string(payload.get("channel"))
        );
    }

    private static int intParam(String raw, int defaultValue) {
        try {
            return Math.max(1, Math.min(100, Integer.parseInt(raw == null || raw.isBlank() ? String.valueOf(defaultValue) : raw)));
        } catch (NumberFormatException error) {
            return defaultValue;
        }
    }

    private static String string(Object... values) {
        for (Object value : values) {
            if (value != null && !String.valueOf(value).isBlank()) {
                return String.valueOf(value);
            }
        }
        return null;
    }

    private static String stringOrDefault(Object value, String defaultValue) {
        return value == null || String.valueOf(value).isBlank() ? defaultValue : String.valueOf(value);
    }
}
