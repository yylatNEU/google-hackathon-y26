package com.parkpulse.backend;

import java.security.MessageDigest;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters;
import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters;
import org.bouncycastle.crypto.signers.Ed25519Signer;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.json.JsonWriteFeature;
import tools.jackson.databind.ObjectMapper;

@Service
public class AgentTrustCredentialCodec {
    private final Environment environment;
    private final ObjectMapper objectMapper;

    public AgentTrustCredentialCodec(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    CertificationMaterial certificationMaterial(String version) {
        String normalizedVersion = version == null || version.isBlank() ? "v1" : version;
        byte[] seed = certificationPrivateSeed(normalizedVersion);
        byte[] publicKey = new Ed25519PrivateKeyParameters(seed, 0).generatePublicKey().getEncoded();
        String kid = "parkpulse-ahp-ed25519-" + sha256(publicKey).substring(0, 12);
        String mode = environment.getProperty("PARKPULSE_AGENT_CERT_ED25519_PRIVATE_KEY_B64") == null
            ? "ed25519_derived_local_demo"
            : "ed25519_env_key";
        return new CertificationMaterial("EdDSA", kid, mode, normalizedVersion, seed, publicKey);
    }

    CertificationMaterial materialForKey(Map<String, Object> key) {
        return "HS256".equals(stringOrDefault(key.get("alg"), ""))
            ? hmacCertificationMaterial(stringOrDefault(key.get("version"), "v1"))
            : certificationMaterial(stringOrDefault(key.get("version"), "v1"));
    }

    List<Map<String, Object>> jwks(List<Map<String, Object>> keys) {
        return keys.stream().map(key -> {
            CertificationMaterial material = certificationMaterial(stringOrDefault(key.get("version"), "v1"));
            Map<String, Object> jwk = orderedMap();
            jwk.put("kid", key.get("kid"));
            jwk.put("alg", key.get("alg"));
            jwk.put("use", "sig");
            jwk.put("status", key.get("status"));
            jwk.put("mode", key.get("mode"));
            jwk.put("version", key.get("version"));
            if ("EdDSA".equals(material.alg()) && stringOrDefault(key.get("kid"), "").equals(material.kid())) {
                jwk.put("kty", "OKP");
                jwk.put("crv", "Ed25519");
                jwk.put("x", base64Url(material.publicKey()));
            } else {
                jwk.put("kty", "oct");
                jwk.put("key_material", "not_published_for_hmac_demo");
            }
            return jwk;
        }).toList();
    }

    String signDelegationClaims(Map<String, Object> claims) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(delegationSecret().getBytes(java.nio.charset.StandardCharsets.UTF_8), "HmacSHA256"));
            return base64Url(mac.doFinal(canonicalJsonBytes(claims)));
        } catch (Exception error) {
            throw new IllegalStateException("Unable to sign delegation token.", error);
        }
    }

    String signCertificationClaims(Map<String, Object> claims, CertificationMaterial material) {
        if ("EdDSA".equals(material.alg())) {
            try {
                Ed25519Signer signer = new Ed25519Signer();
                signer.init(true, new Ed25519PrivateKeyParameters(material.privateSeed(), 0));
                byte[] message = canonicalJsonBytes(claims);
                signer.update(message, 0, message.length);
                return base64Url(signer.generateSignature());
            } catch (Exception error) {
                throw new IllegalStateException("Unable to sign certification claims.", error);
            }
        }
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            byte[] seed = "v1".equals(material.version())
                ? delegationSecret().getBytes(java.nio.charset.StandardCharsets.UTF_8)
                : certificationPrivateSeed(material.version());
            mac.init(new SecretKeySpec(seed, "HmacSHA256"));
            return base64Url(mac.doFinal(canonicalJsonBytes(claims)));
        } catch (Exception error) {
            throw new IllegalStateException("Unable to sign certification claims.", error);
        }
    }

    boolean verifyCertificationClaims(Map<String, Object> claims, String providedSig, Map<String, Object> key) {
        CertificationMaterial material = materialForKey(key);
        String kid = stringOrDefault(claims.get("kid"), "");
        String alg = stringOrDefault(claims.get("alg"), "HS256");
        if (!kid.equals(material.kid()) || !alg.equals(material.alg())) {
            return false;
        }
        if ("EdDSA".equals(material.alg())) {
            try {
                return verifyEd25519(material.publicKey(), canonicalJsonBytes(claims), base64UrlDecode(providedSig));
            } catch (IllegalArgumentException error) {
                return false;
            }
        }
        return constantTimeEquals(providedSig, signCertificationClaims(claims, material));
    }

    boolean constantTimeEquals(String left, String right) {
        return MessageDigest.isEqual(
            left.getBytes(java.nio.charset.StandardCharsets.US_ASCII),
            right.getBytes(java.nio.charset.StandardCharsets.US_ASCII)
        );
    }

    private CertificationMaterial hmacCertificationMaterial(String version) {
        String normalizedVersion = version == null || version.isBlank() ? "v1" : version;
        byte[] digestSource = "v1".equals(normalizedVersion)
            ? delegationSecret().getBytes(java.nio.charset.StandardCharsets.UTF_8)
            : (delegationSecret() + ":" + normalizedVersion).getBytes(java.nio.charset.StandardCharsets.UTF_8);
        String kid = "parkpulse-ahp-hs256-" + sha256(digestSource).substring(0, 12);
        return new CertificationMaterial("HS256", kid, "local_hmac_demo", normalizedVersion, new byte[0], new byte[0]);
    }

    private byte[] certificationPrivateSeed(String version) {
        String configured = environment.getProperty("PARKPULSE_AGENT_CERT_ED25519_PRIVATE_KEY_B64");
        byte[] seed;
        if (configured != null && !configured.isBlank()) {
            seed = base64UrlDecode(configured);
        } else if ("v1".equals(version)) {
            seed = sha256Bytes(
                delegationSecret().getBytes(java.nio.charset.StandardCharsets.UTF_8),
                ":parkpulse-agent-cert-ed25519".getBytes(java.nio.charset.StandardCharsets.UTF_8)
            );
        } else {
            seed = sha256Bytes(
                delegationSecret().getBytes(java.nio.charset.StandardCharsets.UTF_8),
                (":parkpulse-agent-cert-ed25519:" + version).getBytes(java.nio.charset.StandardCharsets.UTF_8)
            );
        }
        return seed.length == 32 ? seed : sha256Bytes(seed);
    }

    private boolean verifyEd25519(byte[] publicKey, byte[] message, byte[] signature) {
        try {
            Ed25519Signer verifier = new Ed25519Signer();
            verifier.init(false, new Ed25519PublicKeyParameters(publicKey, 0));
            verifier.update(message, 0, message.length);
            return verifier.verifySignature(signature);
        } catch (Exception error) {
            return false;
        }
    }

    private byte[] canonicalJsonBytes(Map<String, Object> claims) {
        try {
            return objectMapper.writer().with(JsonWriteFeature.ESCAPE_NON_ASCII).writeValueAsString(new TreeMap<>(claims)).getBytes(java.nio.charset.StandardCharsets.UTF_8);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to canonicalize JSON claims.", error);
        }
    }

    private String sha256(byte[] value) {
        return HexFormat.of().formatHex(sha256Bytes(value));
    }

    private byte[] sha256Bytes(byte[]... values) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            for (byte[] value : values) {
                digest.update(value);
            }
            return digest.digest();
        } catch (Exception error) {
            throw new IllegalStateException("Unable to compute SHA-256.", error);
        }
    }

    private String base64Url(byte[] value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value);
    }

    private byte[] base64UrlDecode(String value) {
        String padded = value + "=".repeat((4 - value.length() % 4) % 4);
        try {
            return Base64.getUrlDecoder().decode(padded);
        } catch (IllegalArgumentException error) {
            return Base64.getDecoder().decode(value);
        }
    }

    private String delegationSecret() {
        return environment.getProperty("PARKPULSE_DELEGATION_TOKEN_SECRET", "parkpulse-local-agent-handshake-demo-secret");
    }

    private String stringOrDefault(Object first, String defaultValue) {
        return first == null || String.valueOf(first).isBlank() ? defaultValue : String.valueOf(first);
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }

    record CertificationMaterial(String alg, String kid, String mode, String version, byte[] privateSeed, byte[] publicKey) {}
}
