package com.parkpulse.backend;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class CorsConfig implements WebMvcConfigurer {
    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**")
            .allowedOriginPatterns("http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*")
            .allowedMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
            .allowedHeaders("authorization", "content-type", "x-parkpulse-role", "x-parkpulse-role-token")
            .exposedHeaders("content-type", "x-parkpulse-spring-gateway")
            .maxAge(3600);
        registry.addMapping("/health")
            .allowedOriginPatterns("http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*")
            .allowedMethods("GET", "OPTIONS")
            .allowedHeaders("*")
            .maxAge(3600);
        registry.addMapping("/readyz")
            .allowedOriginPatterns("http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*")
            .allowedMethods("GET", "OPTIONS")
            .allowedHeaders("*")
            .maxAge(3600);
    }
}
