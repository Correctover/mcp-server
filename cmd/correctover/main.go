package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"strings"

	"correctover"
)

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Correctover MCP Server — CLI Entry Point
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//
// Usage:
//   correctover mcp --providers deepseek,kimi,openai
//   correctover chat --prompt "Hello" --model deepseek-chat
//   correctover list-providers
//
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

func main() {
	log.SetFlags(0) // no timestamps on stderr (clean MCP protocol)
	log.SetPrefix("")

	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}

	subcommand := os.Args[1]

	switch subcommand {
	case "mcp":
		runMCP(os.Args[2:])
	case "chat":
		runChat(os.Args[2:])
	case "list-providers", "providers":
		listProviders(os.Args[2:])
	case "version":
		fmt.Println("correctover v0.1.0")
	case "help":
		printUsage()
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand: %s\n", subcommand)
		printUsage()
		os.Exit(1)
	}
}

func printUsage() {
	fmt.Print(`Correctover — MCP Reliability Layer for AI Tools

Usage:
  correctover mcp [flags]          Start MCP stdio server
  correctover chat [flags]         Direct chat (for testing)
  correctover list-providers       List available providers
  correctover version              Print version

MCP Flags:
  --providers string   Comma-separated provider list (default: deepseek,kimi,openai)

Chat Flags:
  --prompt string      User prompt (required)
  --model string       Model name (default: deepseek-chat)
  --providers string   Provider priority (default: deepseek,kimi,openai)
  --system string      System prompt
  --timeout int        Per-provider timeout in seconds (default: 30)

Examples:
  correctover mcp --providers deepseek,kimi,openai
  correctover chat --prompt "Hello" --model deepseek-chat
`)
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// MCP Server Mode
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

func runMCP(args []string) {
	fs := flag.NewFlagSet("mcp", flag.ExitOnError)
	providersFlag := fs.String("providers", "deepseek,kimi,openai", "Comma-separated provider list")
	_ = fs.Parse(args)

	providerNames := parseProviders(*providersFlag)

	engine, err := correctover.NewEngine(providerNames)
	if err != nil {
		log.Fatalf("engine init: %v", err)
	}

	// Log to stderr so MCP stdout protocol is clean
	enabledList := strings.Join(providerNames, ", ")
	fmt.Fprintf(os.Stderr, "[correctover] engine ready — providers: %s\n", enabledList)

	server := correctover.NewMCPServer(engine)
	ctx := context.Background()
	if err := server.Serve(ctx); err != nil {
		log.Fatalf("server error: %v", err)
	}
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Direct Chat Mode (testing)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

func runChat(args []string) {
	fs := flag.NewFlagSet("chat", flag.ExitOnError)
	prompt := fs.String("prompt", "", "User prompt (required)")
	model := fs.String("model", "deepseek-chat", "Model name")
	providersFlag := fs.String("providers", "deepseek,kimi,openai", "Provider priority order")
	system := fs.String("system", "", "System prompt")
	timeout := fs.Int("timeout", 30, "Per-provider timeout")
	_ = fs.Parse(args)

	if *prompt == "" {
		fmt.Fprintln(os.Stderr, "error: --prompt is required")
		os.Exit(1)
	}

	engine, err := correctover.NewEngine(parseProviders(*providersFlag))
	if err != nil {
		log.Fatalf("engine init: %v", err)
	}

	result := engine.Chat(context.Background(), correctover.ChatRequest{
		Prompt:    *prompt,
		Model:     *model,
		Providers: parseProviders(*providersFlag),
		System:    *system,
		Timeout:   *timeout,
	})

	if result.Error != "" {
		fmt.Fprintf(os.Stderr, "error: %s\n", result.Error)
		os.Exit(1)
	}

	fmt.Println(result.Content)
	fmt.Fprintf(os.Stderr, "\n--- Provider: %s | Model: %s | Latency: %dms | Verified: %v ---\n",
		result.Provider, result.Model, result.LatencyMs, result.Verified)
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// List Providers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

func listProviders(args []string) {
	fs := flag.NewFlagSet("list-providers", flag.ExitOnError)
	providersFlag := fs.String("providers", "deepseek,kimi,openai", "Providers to include")
	_ = fs.Parse(args)

	engine, err := correctover.NewEngine(parseProviders(*providersFlag))
	if err != nil {
		log.Fatalf("engine init: %v", err)
	}

	engine.RangeProviders(func(name string, healthy bool, models []string, priority int) {
		status := "✓"
		if !healthy {
			status = "✗"
		}
		fmt.Printf("%s %s (prio=%d): %s\n", status, name, priority, strings.Join(models, ", "))
	})
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Utilities
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

func parseProviders(s string) []string {
	parts := strings.Split(s, ",")
	result := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			result = append(result, p)
		}
	}
	return result
}
