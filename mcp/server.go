package mcp

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sync"
)

const (
	ProtocolVersion = "2025-11-25"
	ServerName      = "correctover-mcp-server"
	ServerVersion   = "1.0.3"
)

type ToolHandler func(args map[string]any) (*ToolCallResult, error)
type PromptHandler func(args map[string]any) (*PromptGetResult, error)

type Server struct {
	tools          map[string]Tool
	handlers       map[string]ToolHandler
	prompts        map[string]Prompt
	promptHandlers map[string]PromptHandler
	mu             sync.RWMutex
	logWriter      io.Writer
}

func NewServer() *Server {
	return &Server{
		tools:          make(map[string]Tool),
		handlers:       make(map[string]ToolHandler),
		prompts:        make(map[string]Prompt),
		promptHandlers: make(map[string]PromptHandler),
	}
}

func (s *Server) SetLogWriter(w io.Writer) {
	s.logWriter = w
}

func (s *Server) log(msg string) {
	if s.logWriter != nil {
		fmt.Fprintf(s.logWriter, "[correctover] %s\n", msg)
	}
}

func (s *Server) RegisterTool(tool Tool, handler ToolHandler) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.tools[tool.Name] = tool
	s.handlers[tool.Name] = handler
	s.log(fmt.Sprintf("registered tool: %s", tool.Name))
}

func (s *Server) RegisterPrompt(prompt Prompt, handler PromptHandler) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.prompts[prompt.Name] = prompt
	s.promptHandlers[prompt.Name] = handler
	s.log(fmt.Sprintf("registered prompt: %s", prompt.Name))
}

func (s *Server) Run() error {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 1024*1024), 10*1024*1024) // 10MB max

	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}

		var req Request
		if err := json.Unmarshal(line, &req); err != nil {
			s.log(fmt.Sprintf("parse error: %v", err))
			continue
		}

		resp := s.handleRequest(&req)
		if resp != nil {
			data, err := json.Marshal(resp)
			if err != nil {
				s.log(fmt.Sprintf("marshal error: %v", err))
				continue
			}
			fmt.Println(string(data))
		}
	}

	return scanner.Err()
}

func (s *Server) handleRequest(req *Request) *Response {
	switch req.Method {
	case "initialize":
		return s.handleInitialize(req)
	case "initialized":
		return nil // notification, no response
	case "ping":
		return &Response{JSONRPC: "2.0", ID: req.ID, Result: map[string]any{}}
	case "tools/list":
		return s.handleToolsList(req)
	case "tools/call":
		return s.handleToolsCall(req)
	case "prompts/list":
		return s.handlePromptsList(req)
	case "prompts/get":
		return s.handlePromptsGet(req)
	default:
		return &Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Error:   &RPCError{Code: -32601, Message: fmt.Sprintf("method not found: %s", req.Method)},
		}
	}
}

func (s *Server) handleInitialize(req *Request) *Response {
	s.log("client initialized")
	return &Response{
		JSONRPC: "2.0",
		ID:      req.ID,
		Result: InitializeResult{
			ProtocolVersion: ProtocolVersion,
			Capabilities: ServerCaps{
				Tools:   &ToolsCap{ListChanged: false},
				Prompts: &PromptsCap{ListChanged: false},
			},
			ServerInfo: Info{
				Name:    ServerName,
				Version: ServerVersion,
			},
			Instructions: "Correctover is the first MCP server that verifies AI outputs in real-time. " +
				"It sits between your AI tool (Cursor, Claude Desktop, Windsurf) and LLM providers (OpenAI, Anthropic, DeepSeek, etc.), " +
				"validating every response across 6 dimensions: structure, schema, latency, cost, identity, and integrity. " +
				"If validation fails, it automatically retries or fails over to another provider — and validates again.\n\n" +
				"## When to use which tool:\n" +
				"- Use **chat** for any LLM interaction — it automatically validates output and self-heals on failure. " +
				"This is the primary tool for most use cases.\n" +
				"- Use **health** to check which providers are configured and ready before starting work.\n" +
				"- Use **providers** to see detailed configuration for all supported providers.\n" +
				"- Use **stats** to review session statistics after a working session.\n\n" +
				"## Configuration:\n" +
				"Set at least one API key via environment variables: OPENAI_API_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, etc. " +
				"Only configured providers are active. Your keys stay on your machine (BYOK — no proxy, no data collection).\n\n" +
				"## Failover ≠ Correctover:\n" +
				"Simple failover just switches providers. Correctover switches AND verifies the output is correct before delivering it. " +
				"Every response passes through 6-dimension validation — if it fails, the engine auto-retries or fails over, then re-validates.",
		},
	}
}

func (s *Server) handleToolsList(req *Request) *Response {
	s.mu.RLock()
	defer s.mu.RUnlock()

	tools := make([]Tool, 0, len(s.tools))
	for _, t := range s.tools {
		tools = append(tools, t)
	}

	return &Response{
		JSONRPC: "2.0",
		ID:      req.ID,
		Result:  ToolsListResult{Tools: tools},
	}
}

func (s *Server) handleToolsCall(req *Request) *Response {
	var params ToolCallParams
	if err := json.Unmarshal(req.Params, &params); err != nil {
		return &Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Error:   &RPCError{Code: -32602, Message: fmt.Sprintf("invalid params: %v", err)},
		}
	}

	s.mu.RLock()
	handler, ok := s.handlers[params.Name]
	s.mu.RUnlock()

	if !ok {
		return &Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Error:   &RPCError{Code: -32602, Message: fmt.Sprintf("unknown tool: %s", params.Name)},
		}
	}

	result, err := handler(params.Arguments)
	if err != nil {
		return &Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result: &ToolCallResult{
				Content: []Content{TextContent(fmt.Sprintf("Error: %v", err))},
				IsError: true,
			},
		}
	}

	return &Response{
		JSONRPC: "2.0",
		ID:      req.ID,
		Result:  result,
	}
}

func (s *Server) handlePromptsList(req *Request) *Response {
	s.mu.RLock()
	defer s.mu.RUnlock()

	prompts := make([]Prompt, 0, len(s.prompts))
	for _, p := range s.prompts {
		prompts = append(prompts, p)
	}

	return &Response{
		JSONRPC: "2.0",
		ID:      req.ID,
		Result:  PromptsListResult{Prompts: prompts},
	}
}

func (s *Server) handlePromptsGet(req *Request) *Response {
	var params struct {
		Name      string         `json:"name"`
		Arguments map[string]any `json:"arguments,omitempty"`
	}
	if err := json.Unmarshal(req.Params, &params); err != nil {
		return &Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Error:   &RPCError{Code: -32602, Message: fmt.Sprintf("invalid params: %v", err)},
		}
	}

	s.mu.RLock()
	handler, ok := s.promptHandlers[params.Name]
	s.mu.RUnlock()

	if !ok {
		return &Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Error:   &RPCError{Code: -32602, Message: fmt.Sprintf("unknown prompt: %s", params.Name)},
		}
	}

	result, err := handler(params.Arguments)
	if err != nil {
		return &Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Error:   &RPCError{Code: -32603, Message: fmt.Sprintf("prompt error: %v", err)},
		}
	}

	return &Response{
		JSONRPC: "2.0",
		ID:      req.ID,
		Result:  result,
	}
}
