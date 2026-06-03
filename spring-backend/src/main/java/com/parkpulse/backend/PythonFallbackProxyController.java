package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class PythonFallbackProxyController {
    private final PythonFallbackProxyService proxyService;
    private final RoleAuthService roleAuthService;

    public PythonFallbackProxyController(PythonFallbackProxyService proxyService, RoleAuthService roleAuthService) {
        this.proxyService = proxyService;
        this.roleAuthService = roleAuthService;
    }

    @GetMapping(value = "/api/park/backend-gateway/status", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> backendGatewayStatus(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_platform_status");
        return proxyService.status();
    }

    @RequestMapping(
        value = {"/api/{*path}", "/readyz/deep"},
        method = {RequestMethod.GET, RequestMethod.POST, RequestMethod.PUT, RequestMethod.PATCH, RequestMethod.DELETE, RequestMethod.OPTIONS}
    )
    public ResponseEntity<byte[]> fallback(HttpServletRequest request, @RequestBody(required = false) byte[] body) {
        return proxyService.forward(request, body);
    }
}
