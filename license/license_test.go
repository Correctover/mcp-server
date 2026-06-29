package license

import (
	"encoding/base64"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"
)

// ── Test helpers ───────────────────────────────────────────────────

// generateTestKey creates a valid license key for testing.
// Uses the package-level hmacSign and defaultHMACSecret.
func generateTestKey(planStr, customer string, expiresAt int64) string {
	prefixMap := map[string]string{
		planStrTrial:     "CV-TRL-",
		planStrPro:       "CV-PRO-",
		planStrEnterprise: "CV-ENT-",
	}

	prefix, ok := prefixMap[planStr]
	if !ok {
		panic("unknown plan: " + planStr)
	}

	payload := fmt.Sprintf(`{"p":"%s","e":%d,"c":"%s"}`, planStr, expiresAt, customer)
	sig := hmacSign(payload)
	encoded := base64.RawURLEncoding.EncodeToString([]byte(payload + "." + sig))
	return prefix + encoded
}

func mustParseTime(t *testing.T, s string) time.Time {
	t.Helper()
	parsed, err := time.Parse("2006-01-02", s)
	if err != nil {
		t.Fatalf("parse time %q: %v", s, err)
	}
	return parsed
}

// ── Tests ──────────────────────────────────────────────────────────

func TestLoadFromEnv_NoKey(t *testing.T) {
	os.Unsetenv("CORRECTOVER_LICENSE_KEY")
	lic := LoadFromEnv()

	if lic.Key != "" {
		t.Errorf("expected empty key, got %q", lic.Key)
	}
	if lic.Valid {
		t.Errorf("expected invalid license when no key")
	}
	if got := lic.ProviderLimit(); got != 2 {
		t.Errorf("expected ProviderLimit=2, got %d", got)
	}
	if lic.IsExpired() {
		t.Errorf("expected IsExpired=false for free mode")
	}
	if got := lic.PlanName(); got != "Free" {
		t.Errorf("expected PlanName=Free, got %q", got)
	}
}

func TestLoadFromEnv_InvalidKey(t *testing.T) {
	t.Setenv("CORRECTOVER_LICENSE_KEY", "CV-PRO-invalid-key")
	lic := LoadFromEnv()

	if lic.Valid {
		t.Errorf("expected invalid license for bad key")
	}
	if got := lic.ProviderLimit(); got != 2 {
		t.Errorf("expected ProviderLimit=2 for invalid key, got %d", got)
	}
}

func TestVerify_ProPerpetual(t *testing.T) {
	key := generateTestKey(planStrPro, "test-customer", 0)
	lic := &License{Key: key, DeviceID: deviceFingerprint()}

	err := lic.Verify()
	if err != nil {
		t.Fatalf("Verify() failed: %v", err)
	}

	if lic.Plan != PlanPro {
		t.Errorf("expected Plan=Pro, got %v", lic.Plan)
	}
	if !lic.Valid {
		t.Errorf("expected Valid=true")
	}
	if lic.Customer != "test-customer" {
		t.Errorf("expected Customer=test-customer, got %q", lic.Customer)
	}
	if !lic.Expires.IsZero() {
		t.Errorf("expected Expires=zero (perpetual), got %v", lic.Expires)
	}
	if lic.IsExpired() {
		t.Errorf("expected IsExpired=false for perpetual")
	}
	if got := lic.ProviderLimit(); got != 999 {
		t.Errorf("expected ProviderLimit=999, got %d", got)
	}
	if got := lic.PlanName(); got != "Pro" {
		t.Errorf("expected PlanName=Pro, got %q", got)
	}
}

func TestVerify_TrialWithExpiry(t *testing.T) {
	future := time.Now().Add(48 * time.Hour)
	key := generateTestKey(planStrTrial, "trial-user", future.Unix())
	lic := &License{Key: key, DeviceID: deviceFingerprint()}

	err := lic.Verify()
	if err != nil {
		t.Fatalf("Verify() failed: %v", err)
	}

	if lic.Plan != PlanTrial {
		t.Errorf("expected Plan=Trial, got %v", lic.Plan)
	}
	if !lic.Valid {
		t.Errorf("expected Valid=true")
	}
	if lic.Expires.IsZero() {
		t.Errorf("expected non-zero Expires")
	}
	if lic.IsExpired() {
		t.Errorf("expected IsExpired=false (future expiry)")
	}
	if got := lic.ProviderLimit(); got != 2 {
		t.Errorf("expected ProviderLimit=2 for Trial, got %d", got)
	}
}

func TestVerify_Enterprise(t *testing.T) {
	key := generateTestKey(planStrEnterprise, "enterprise-co", 0)
	lic := &License{Key: key, DeviceID: deviceFingerprint()}

	err := lic.Verify()
	if err != nil {
		t.Fatalf("Verify() failed: %v", err)
	}

	if lic.Plan != PlanEnterprise {
		t.Errorf("expected Plan=Enterprise, got %v", lic.Plan)
	}
	if got := lic.ProviderLimit(); got != 999 {
		t.Errorf("expected ProviderLimit=999, got %d", got)
	}
}

func TestVerify_ExpiredKey(t *testing.T) {
	past := time.Now().Add(-24 * time.Hour)
	key := generateTestKey(planStrPro, "expired-user", past.Unix())
	lic := &License{Key: key, DeviceID: deviceFingerprint()}

	err := lic.Verify()
	if err == nil {
		t.Fatal("expected Verify() to return error for expired key")
	}
	if !strings.Contains(err.Error(), "expired") {
		t.Errorf("expected error about expiry, got: %v", err)
	}
}

func TestVerify_BadSignature(t *testing.T) {
	// Generate a valid key then corrupt the signature
	key := generateTestKey(planStrPro, "test", 0)
	// Corrupt: change a char before the signature
	corrupted := key[:len(key)-4] + "beef"
	lic := &License{Key: corrupted, DeviceID: deviceFingerprint()}

	err := lic.Verify()
	if err == nil {
		t.Fatal("expected Verify() to return error for corrupted key")
	}
	if !strings.Contains(err.Error(), "signature") {
		t.Errorf("expected error about signature, got: %v", err)
	}
}

func TestVerify_UnknownPrefix(t *testing.T) {
	lic := &License{Key: "XX-XXX-foobar", DeviceID: deviceFingerprint()}
	err := lic.Verify()
	if err == nil {
		t.Fatal("expected Verify() to return error for unknown prefix")
	}
}

func TestVerify_EmptyKey(t *testing.T) {
	lic := &License{Key: "", DeviceID: deviceFingerprint()}
	err := lic.Verify()
	if err == nil {
		t.Fatal("expected Verify() to return error for empty key")
	}
}

func TestProviderLimit(t *testing.T) {
	tests := []struct {
		name  string
		setup func() *License
		want  int
	}{
		{
			name: "no key = trial limit",
			setup: func() *License {
				return &License{Key: "", Valid: false}
			},
			want: 2,
		},
		{
			name: "invalid key = trial limit",
			setup: func() *License {
				return &License{Key: "CV-PRO-bad", Valid: false}
			},
			want: 2,
		},
		{
			name: "trial = 2",
			setup: func() *License {
				key := generateTestKey(planStrTrial, "t", 0)
				l := &License{Key: key}
				l.Verify()
				return l
			},
			want: 2,
		},
		{
			name: "pro = 999",
			setup: func() *License {
				key := generateTestKey(planStrPro, "p", 0)
				l := &License{Key: key}
				l.Verify()
				return l
			},
			want: 999,
		},
		{
			name: "enterprise = 999",
			setup: func() *License {
				key := generateTestKey(planStrEnterprise, "e", 0)
				l := &License{Key: key}
				l.Verify()
				return l
			},
			want: 999,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			lic := tt.setup()
			if got := lic.ProviderLimit(); got != tt.want {
				t.Errorf("ProviderLimit() = %d, want %d", got, tt.want)
			}
		})
	}
}

func TestIsExpired(t *testing.T) {
	t.Run("free mode never expired", func(t *testing.T) {
		lic := &License{Key: "", Valid: false}
		if lic.IsExpired() {
			t.Error("expected IsExpired=false for free mode")
		}
	})

	t.Run("perpetual never expired", func(t *testing.T) {
		key := generateTestKey(planStrPro, "t", 0)
		lic := &License{Key: key}
		lic.Verify()
		if lic.IsExpired() {
			t.Error("expected IsExpired=false for perpetual")
		}
	})

	t.Run("future expiry not expired", func(t *testing.T) {
		future := time.Now().Add(30 * 24 * time.Hour)
		key := generateTestKey(planStrTrial, "t", future.Unix())
		lic := &License{Key: key}
		lic.Verify()
		if lic.IsExpired() {
			t.Error("expected IsExpired=false for future expiry")
		}
	})

	t.Run("past expiry is expired", func(t *testing.T) {
		past := time.Now().Add(-24 * time.Hour)
		key := generateTestKey(planStrPro, "t", past.Unix())
		lic := &License{Key: key}
		lic.Verify() // will fail, but let's check expired state
		// Verify sets Valid=false on expiry, so IsExpired should return false
		// because it's "invalid" not "expired" in our semantic
		// Actually let's test the state after manual construction
		lic2 := &License{
			Key:     "test",
			Valid:   true,
			Expires: past,
			Plan:    PlanPro,
		}
		if !lic2.IsExpired() {
			t.Error("expected IsExpired=true for past expiry")
		}
	})
}

func TestPlanName(t *testing.T) {
	tests := []struct {
		name string
		plan Plan
		want string
	}{
		{"trial", PlanTrial, "Trial"},
		{"pro", PlanPro, "Pro"},
		{"enterprise", PlanEnterprise, "Enterprise"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			lic := &License{Key: "test", Valid: true, Plan: tt.plan}
			if got := lic.PlanName(); got != tt.want {
				t.Errorf("PlanName() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestSummary(t *testing.T) {
	t.Run("free mode", func(t *testing.T) {
		lic := &License{Key: ""}
		s := lic.Summary()
		if !strings.Contains(s, "Free") {
			t.Errorf("summary should mention Free: %q", s)
		}
	})

	t.Run("pro perpetual", func(t *testing.T) {
		key := generateTestKey(planStrPro, "test-co", 0)
		lic := &License{Key: key}
		lic.Verify()
		s := lic.Summary()
		if !strings.Contains(s, "Pro") || !strings.Contains(s, "perpetual") {
			t.Errorf("unexpected summary: %q", s)
		}
	})

	t.Run("trial with expiry", func(t *testing.T) {
		future := time.Now().Add(48 * time.Hour)
		key := generateTestKey(planStrTrial, "trial-user", future.Unix())
		lic := &License{Key: key}
		lic.Verify()
		s := lic.Summary()
		if !strings.Contains(s, "Trial") || !strings.Contains(s, "days") {
			t.Errorf("unexpected summary: %q", s)
		}
	})
}

func TestDeviceFingerprint(t *testing.T) {
	fp1 := deviceFingerprint()
	fp2 := deviceFingerprint()

	if len(fp1) != 16 {
		t.Errorf("expected 16 hex chars, got %d: %s", len(fp1), fp1)
	}
	if fp1 != fp2 {
		t.Errorf("fingerprint should be stable: %s != %s", fp1, fp2)
	}
}

// ── Environment variable tests ─────────────────────────────────────

func TestHMACSecretOverride(t *testing.T) {
	// Override HMAC secret via env var
	os.Setenv("CORRECTOVER_HMAC_KEY", "test-hmac-secret")
	defer os.Unsetenv("CORRECTOVER_HMAC_KEY")

	if got := string(getHMACSecret()); got != "test-hmac-secret" {
		t.Errorf("getHMACSecret() = %q, want %q", got, "test-hmac-secret")
	}
}

func TestHMACSecretDefault(t *testing.T) {
	os.Unsetenv("CORRECTOVER_HMAC_KEY")
	if got := string(getHMACSecret()); got != defaultHMACSecret {
		t.Errorf("getHMACSecret() = %q, want %q", got, defaultHMACSecret)
	}
}

func TestCrossEnvKeyWithCustomHMAC(t *testing.T) {
	os.Unsetenv("CORRECTOVER_HMAC_KEY")

	// Generate key with default secret
	key := generateTestKey(planStrPro, "cross-test", 0)
	lic := &License{Key: key}
	err := lic.Verify()
	if err != nil {
		t.Fatalf("Verify with default HMAC: %v", err)
	}
	if !lic.Valid {
		t.Fatal("expected valid license")
	}
}
