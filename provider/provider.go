package provider

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"sync"
	"time"
)

// ---- Provider 定义 ----

type Provider struct {
	Name       string `json:"name"`
	BaseURL    string `json:"baseURL"`
	APIKey     string `json:"-"`
	Model      string `json:"model"`
	EnvKey     string `json:"envKey"`     // env var name for API key
	MaxRetries int    `json:"maxRetries"`
	Timeout    int    `json:"timeout"`    // seconds
	Priority   int    `json:"priority"`   // lower = higher priority
	Enabled    bool   `json:"enabled"`
}

// ---- 请求/响应结构 ----

type ChatRequest struct {
	Model    string    `json:"model"`
	Messages []Message `json:"messages"`
	Stream   bool      `json:"stream"`
	// OpenAI-compatible fields
	Temperature      *float64 `json:"temperature,omitempty"`
	MaxTokens        *int     `json:"max_tokens,omitempty"`
	TopP             *float64 `json:"top_p,omitempty"`
	Stop             any      `json:"stop,omitempty"`
	PresencePenalty  *float64 `json:"presence_penalty,omitempty"`
}

type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type ChatResponse struct {
	ID      string   `json:"id"`
	Choices []Choice `json:"choices"`
	Usage   Usage    `json:"usage"`
	Model   string   `json:"model"`
	// Metadata added by Correctover
	CorrectoverMeta *ResponseMeta `json:"_correctover,omitempty"`
}

type Choice struct {
	Index        int     `json:"index"`
	Message      Message `json:"message"`
	FinishReason string  `json:"finish_reason"`
}

type Usage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

type ResponseMeta struct {
	Provider       string  `json:"provider"`
	LatencyMs      int64   `json:"latency_ms"`
	ValidationPassed bool  `json:"validation_passed"`
	ValidationDetails map[string]bool `json:"validation_details,omitempty"`
	FailoverCount  int     `json:"failover_count"`
	RetryCount     int     `json:"retry_count"`
	CostUSD        float64 `json:"cost_usd,omitempty"`
}

// ---- Provider Manager ----

type Manager struct {
	providers map[string]*Provider
	mu        sync.RWMutex
	client    *http.Client
}

func NewManager() *Manager {
	m := &Manager{
		providers: make(map[string]*Provider),
		client: &http.Client{
			Timeout: 120 * time.Second,
		},
	}
	m.loadFromEnv()
	return m
}

func (m *Manager) loadFromEnv() {
	definitions := []struct {
		name    string
		baseURL string
		envKey  string
		model   string
	}{
		{"openai", "https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"},
		{"anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "claude-3-haiku-20240307"},
		{"deepseek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", "deepseek-chat"},
		{"moonshot", "https://api.moonshot.cn/v1", "MOONSHOT_API_KEY", "moonshot-v1-8k"},
		{"zhipu", "https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY", "glm-4-flash"},
		{"qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY", "qwen-turbo"},
		{"siliconflow", "https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY", "deepseek-ai/DeepSeek-V3"},
		{"groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.1-8b-instant"},
		{"together", "https://api.together.xyz/v1", "TOGETHER_API_KEY", "meta-llama/Llama-3-8b-chat-hf"},
	}

	for _, def := range definitions {
		key := os.Getenv(def.envKey)
		if key == "" {
			continue
		}
		// Allow base URL override via environment variable (for proxy/mirror users)
		// e.g. OPENAI_BASE_URL=https://your-proxy.com/v1
		baseURL := def.baseURL
		envBaseURLName := ""
		switch def.name {
		case "openai":
			envBaseURLName = "OPENAI_BASE_URL"
		case "anthropic":
			envBaseURLName = "ANTHROPIC_BASE_URL"
		case "deepseek":
			envBaseURLName = "DEEPSEEK_BASE_URL"
		case "moonshot":
			envBaseURLName = "MOONSHOT_BASE_URL"
		case "zhipu":
			envBaseURLName = "ZHIPU_BASE_URL"
		case "qwen":
			envBaseURLName = "DASHSCOPE_BASE_URL"
		case "siliconflow":
			envBaseURLName = "SILICONFLOW_BASE_URL"
		case "groq":
			envBaseURLName = "GROQ_BASE_URL"
		case "together":
			envBaseURLName = "TOGETHER_BASE_URL"
		}
		if envBaseURLName != "" {
			if envVal := os.Getenv(envBaseURLName); envVal != "" {
				baseURL = envVal
			}
		}
		m.providers[def.name] = &Provider{
			Name:       def.name,
			BaseURL:    baseURL,
			APIKey:     key,
			Model:      def.model,
			EnvKey:     def.envKey,
			MaxRetries: 2,
			Timeout:    60,
			Priority:   len(m.providers) + 1,
			Enabled:    true,
		}
	}
}

func (m *Manager) AvailableProviders() []string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var names []string
	for name, p := range m.providers {
		if p.Enabled {
			names = append(names, name)
		}
	}
	return names
}

func (m *Manager) Get(name string) (*Provider, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	p, ok := m.providers[name]
	return p, ok
}

func (m *Manager) Call(providerName string, req *ChatRequest) (*ChatResponse, int64, error) {
	p, ok := m.Get(providerName)
	if !ok {
		return nil, 0, fmt.Errorf("provider not found: %s", providerName)
	}

	if req.Model == "" || req.Model == "auto" {
		req.Model = p.Model
	}

	body, err := json.Marshal(req)
	if err != nil {
		return nil, 0, fmt.Errorf("marshal request: %w", err)
	}

	httpReq, err := http.NewRequest("POST", p.BaseURL+"/chat/completions", bytes.NewReader(body))
	if err != nil {
		return nil, 0, fmt.Errorf("create request: %w", err)
	}

	httpReq.Header.Set("Content-Type", "application/json")

	// Set auth header based on provider
	if providerName == "anthropic" {
		httpReq.Header.Set("x-api-key", p.APIKey)
		httpReq.Header.Set("anthropic-version", "2023-06-01")
	} else {
		httpReq.Header.Set("Authorization", "Bearer "+p.APIKey)
	}

	start := time.Now()
	resp, err := m.client.Do(httpReq)
	latency := time.Since(start).Milliseconds()
	if err != nil {
		return nil, latency, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, latency, fmt.Errorf("read response: %w", err)
	}

	if resp.StatusCode != 200 {
		return nil, latency, fmt.Errorf("provider %s returned %d: %s", providerName, resp.StatusCode, string(respBody))
	}

	var chatResp ChatResponse
	if err := json.Unmarshal(respBody, &chatResp); err != nil {
		return nil, latency, fmt.Errorf("parse response: %w", err)
	}

	return &chatResp, latency, nil
}
