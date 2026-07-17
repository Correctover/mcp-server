// Copyright 2024-2026 Correctover Team
// Licensed under the Apache License, Version 2.0 (the "License")
//
// License verification system for Correctover MCP Server.
//
// Architecture:
//   - Offline verification via HMAC-SHA256
//   - Device fingerprint (MAC + hostname → SHA256)
//   - Plan-based provider limiting
//   - Non-blocking startup; gates at feature usage
//
// Usage:
//     lic := license.LoadFromEnv()
//     limit := lic.ProviderLimit()  // max providers allowed
//
// Environment variables:
//   CORRECTOVER_LICENSE_KEY  — License key (CV-TRL-*, CV-PRO-*, CV-ENT-*)
//   CORRECTOVER_HMAC_KEY    — Override embedded HMAC secret (optional)

package license

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"strings"
	"sync"
	"time"
)

// Plan represents the license tier.
type Plan int

const (
	PlanTrial     Plan = iota // 2 providers, time-limited
	PlanPro                   // Unlimited providers, full features
	PlanEnterprise            // Custom limits, private deployment
)

// plan strings (used in license key payload)
const (
	planStrTrial     = "trial"
	planStrPro       = "pro"
	planStrEnterprise = "enterprise"
	planStrFree      = "free"
)

// planLabels maps plan to human-readable labels.
var planLabels = map[Plan]string{
	PlanTrial:     "Trial",
	PlanPro:       "Pro",
	PlanEnterprise: "Enterprise",
}

// planProviderLimits maps plan to max providers.
var planProviderLimits = map[Plan]int{
	PlanTrial:     2,
	PlanPro:       999, // effectively unlimited
	PlanEnterprise: 999,
}

// planKeyPrefixes maps license key prefix → plan.
// Supports both Correctover (CV-) and legacy NeuralBridge (NB-) prefixes.
// Legacy prefixes keep backward compatibility with existing issued keys.
var planKeyPrefixes = map[string]struct {
	plan    Plan
	planStr string
}{
	"CV-TRL-": {PlanTrial, planStrTrial},
	"CV-PRO-": {PlanPro, planStrPro},
	"CV-ENT-": {PlanEnterprise, planStrEnterprise},
	// Legacy NeuralBridge prefixes (backward compatibility)
	"NB-TRL-": {PlanTrial, planStrTrial},
	"NB-PRO-": {PlanPro, planStrPro},
	"NB-ENT-": {PlanEnterprise, planStrEnterprise},
	"NB-MON-": {PlanPro, planStrPro},     // monthly → Pro tier
	"NB-ANN-": {PlanPro, planStrPro},     // annual → Pro tier
	"NB-LTM-": {PlanEnterprise, planStrEnterprise}, // lifetime → Enterprise tier
}

// defaultHMACSecret is compiled into the binary. Override at build time:
//
//	go build -ldflags="-X github.com/Correctover/mcp-server/license.defaultHMACSecret=real-secret"
//
// Or at runtime via CORRECTOVER_HMAC_KEY env var.
var defaultHMACSecret = "correctover-mcp-hmac-v1-2026"

// ── License ────────────────────────────────────────────────────────

// License represents a parsed and verified Correctover license.
type License struct {
	Key      string    `json:"key"`
	Plan     Plan      `json:"plan"`
	Expires  time.Time `json:"expires"`
	DeviceID string    `json:"device_id"`
	Valid    bool      `json:"valid"`
	Customer string    `json:"customer"`
	Message  string    `json:"message"`

	mu sync.RWMutex
}

// ── Public API ─────────────────────────────────────────────────────

// LoadFromEnv reads CORRECTOVER_LICENSE_KEY and returns a License.
// Returns a Free (unlicensed) License when the env var is unset or empty.
func LoadFromEnv() *License {
	key := os.Getenv("CORRECTOVER_LICENSE_KEY")
	lic := &License{
		Key:      key,
		DeviceID: deviceFingerprint(),
	}

	if key == "" {
		lic.Message = "No license key. Using Free mode (max 2 providers). Set CORRECTOVER_LICENSE_KEY for Pro."
		return lic
	}

	// Verify the key
	maybeErr := lic.Verify()
	if maybeErr != nil {
		lic.Message = fmt.Sprintf("License invalid: %v. Using Free mode (max 2 providers).", maybeErr)
		return lic
	}

	lic.Message = lic.formatMessage()
	return lic
}

// Verify re-verifies the license key. Returns nil on success or an error
// describing why verification failed.
func (l *License) Verify() error {
	l.mu.Lock()
	defer l.mu.Unlock()

	if l.Key == "" {
		l.Valid = false
		return fmt.Errorf("no license key provided")
	}

	// Determine plan from key prefix
	var matched bool
	var isLegacyPrefix bool
	for prefix, info := range planKeyPrefixes {
		if strings.HasPrefix(l.Key, prefix) {
			matched = true
			isLegacyPrefix = strings.HasPrefix(prefix, "NB-")
			l.Plan = info.plan
			encoded := l.Key[len(prefix):]

			payload, sig, err := decodeKey(encoded)
			if err != nil {
				l.Valid = false
				return fmt.Errorf("decode failed: %w", err)
			}

			// Try primary HMAC secret first
			sigErr := verifySignature(payload, sig)
			if sigErr != nil && isLegacyPrefix {
				// Legacy NB- prefix keys may be signed with a different (historical) secret.
				// Try each known legacy secret as fallback.
				for _, legacySecret := range legacyHMACSecrets {
					sigErr = verifySignatureWithSecret(payload, sig, []byte(legacySecret))
					if sigErr == nil {
						break
					}
				}
			}
			if sigErr != nil {
				l.Valid = false
				return fmt.Errorf("signature invalid: %w", sigErr)
			}

			licInfo, err := parsePayload(payload)
			if err != nil {
				l.Valid = false
				return fmt.Errorf("payload invalid: %w", err)
			}

			l.Plan = licInfo.plan
			l.Expires = licInfo.expires
			l.Customer = licInfo.customer
			l.Valid = true
			break
		}
	}

	if !matched {
		l.Valid = false
		return fmt.Errorf("unknown license key prefix; expected CV-TRL-, CV-PRO-, CV-ENT-, or legacy NB- prefix")
	}

	return nil
}

// ProviderLimit returns the maximum number of LLM providers allowed.
func (l *License) ProviderLimit() int {
	l.mu.RLock()
	defer l.mu.RUnlock()

	if !l.Valid || l.Key == "" {
		return planProviderLimits[PlanTrial] // Free = Trial limit
	}

	limit, ok := planProviderLimits[l.Plan]
	if !ok {
		return planProviderLimits[PlanTrial]
	}
	return limit
}

// IsExpired returns true if a previously valid license has expired.
// Returns false for unlicensed (Free) mode or perpetual licenses.
func (l *License) IsExpired() bool {
	l.mu.RLock()
	defer l.mu.RUnlock()

	if !l.Valid || l.Key == "" {
		return false // Free mode — not expired, just unlicensed
	}
	if l.Expires.IsZero() {
		return false // perpetual / no expiry
	}
	return time.Now().After(l.Expires)
}

// PlanName returns the human-readable name of the current plan.
func (l *License) PlanName() string {
	l.mu.RLock()
	defer l.mu.RUnlock()

	if !l.Valid || l.Key == "" {
		return "Free"
	}
	if name, ok := planLabels[l.Plan]; ok {
		return name
	}
	return "Unknown"
}

// Summary returns a one-line human-readable license status.
func (l *License) Summary() string {
	l.mu.RLock()
	defer l.mu.RUnlock()

	if !l.Valid || l.Key == "" {
		limit := planProviderLimits[PlanTrial]
		return fmt.Sprintf("Free mode — max %d providers. Set CORRECTOVER_LICENSE_KEY for Pro.", limit)
	}

	label := planLabels[l.Plan]
	limit := planProviderLimits[l.Plan]

	if l.Expires.IsZero() {
		return fmt.Sprintf("%s — perpetual | max %d providers", label, limit)
	}

	remaining := time.Until(l.Expires)
	if remaining <= 0 {
		return fmt.Sprintf("%s — EXPIRED (was %s)", label, l.Expires.Format("2006-01-02"))
	}

	days := int(remaining.Hours() / 24)
	return fmt.Sprintf("%s — %d days remaining | max %d providers", label, days, limit)
}

// ── Internal: key parsing ──────────────────────────────────────────

type licensePayload struct {
	plan     Plan
	expires  time.Time
	customer string
}

// decodeKey splits the encoded portion into payload and signature hex.
func decodeKey(encoded string) (payload, sig string, err error) {
	// Add Base64 URL padding
	switch len(encoded) % 4 {
	case 2:
		encoded += "=="
	case 3:
		encoded += "="
	}

	decoded, decErr := base64.URLEncoding.DecodeString(encoded)
	if decErr != nil {
		return "", "", fmt.Errorf("base64 decode: %w", decErr)
	}

	parts := strings.SplitN(string(decoded), ".", 2)
	if len(parts) != 2 {
		return "", "", fmt.Errorf("missing '.' separator between payload and signature")
	}

	return parts[0], parts[1], nil
}

// verifySignature checks the HMAC-SHA256 signature.
func verifySignature(payload, sigHex string) error {
	expected := hmacSign(payload)
	if !hmac.Equal([]byte(sigHex), []byte(expected)) {
		return fmt.Errorf("HMAC mismatch")
	}
	return nil
}

// verifySignatureWithSecret is like verifySignature but with an explicit secret.
// Used for legacy NB- prefix key fallback verification.
func verifySignatureWithSecret(payload, sigHex string, secret []byte) error {
	mac := hmac.New(sha256.New, secret)
	mac.Write([]byte(payload))
	expected := hex.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(sigHex), []byte(expected)) {
		return fmt.Errorf("HMAC mismatch")
	}
	return nil
}

// parsePayload extracts plan, expiry, and customer from the JSON payload.
func parsePayload(payloadStr string) (*licensePayload, error) {
	var raw struct {
		P string `json:"p"` // plan
		E int64  `json:"e"` // expires_at (unix timestamp, 0 = perpetual)
		C string `json:"c"` // customer
	}
	if err := json.Unmarshal([]byte(payloadStr), &raw); err != nil {
		return nil, fmt.Errorf("JSON parse: %w", err)
	}

	if raw.P == "" {
		return nil, fmt.Errorf("missing plan field 'p'")
	}

	// Map plan string to Plan enum
	planMap := map[string]Plan{
		planStrTrial:     PlanTrial,
		planStrPro:       PlanPro,
		planStrEnterprise: PlanEnterprise,
		// Legacy plan names (backward compatibility with FC-generated keys)
		"monthly": PlanPro,
		"annual":  PlanPro,
		"lifetime": PlanEnterprise,
	}

	plan, ok := planMap[raw.P]
	if !ok {
		return nil, fmt.Errorf("unknown plan: %s", raw.P)
	}

	var expires time.Time
	if raw.E > 0 {
		expires = time.Unix(raw.E, 0)
	}

	// Check expiry
	if raw.E > 0 && time.Now().Unix() > raw.E {
		return nil, fmt.Errorf("license expired on %s", expires.Format("2006-01-02"))
	}

	return &licensePayload{
		plan:     plan,
		expires:  expires,
		customer: raw.C,
	}, nil
}

// formatMessage builds a human-readable message for a valid license.
func (l *License) formatMessage() string {
	label := planLabels[l.Plan]
	if l.Expires.IsZero() {
		return fmt.Sprintf("Valid %s license for %s (perpetual)", label, l.Customer)
	}
	return fmt.Sprintf("Valid %s license for %s (expires %s)",
		label, l.Customer, l.Expires.Format("2006-01-02"))
}

// ── Internal: device fingerprint ───────────────────────────────────

// deviceFingerprint generates a unique device identifier.
// Combines hostname + MAC addresses → SHA256 hex.
func deviceFingerprint() string {
	hostname, hostErr := os.Hostname()
	if hostErr != nil {
		hostname = "unknown"
	}

	macs := activeMACAddresses()
	raw := hostname + "|" + strings.Join(macs, ",")
	hash := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(hash[:8]) // first 8 bytes = 16 hex chars
}

// activeMACAddresses returns MAC addresses of active (UP) interfaces.
func activeMACAddresses() []string {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil
	}

	var macs []string
	for _, iface := range ifaces {
		if iface.Flags&net.FlagUp == 0 {
			continue
		}
		if len(iface.HardwareAddr) == 0 {
			continue
		}
		// Skip loopback and tunnel interfaces
		if iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		macs = append(macs, iface.HardwareAddr.String())
	}
	return macs
}

// ── Internal: HMAC ─────────────────────────────────────────────────

// hmacSign computes HMAC-SHA256 of the data using the configured secret.
func hmacSign(data string) string {
	secret := getHMACSecret()
	mac := hmac.New(sha256.New, secret)
	mac.Write([]byte(data))
	return hex.EncodeToString(mac.Sum(nil))
}

// legacyHMACSecrets is a list of known old HMAC secrets that are tried as fallback
// for legacy NB- prefix keys. This ensures previously issued keys remain valid.
var legacyHMACSecrets = []string{
	"",                        // FC default when env var not set
	"NB-SK-2026-6c5ce7-a",    // Previous FC NB_HMAC_SECRET value
}

// getHMACSecret returns the HMAC key: env var overrides the compiled default.
// Priority: CORRECTOVER_HMAC_SECRET > CORRECTOVER_HMAC_KEY > compiled defaultHMACSecret.
func getHMACSecret() []byte {
	if env := os.Getenv("CORRECTOVER_HMAC_SECRET"); env != "" {
		return []byte(env)
	}
	if env := os.Getenv("CORRECTOVER_HMAC_KEY"); env != "" {
		return []byte(env)
	}
	return []byte(defaultHMACSecret)
}
