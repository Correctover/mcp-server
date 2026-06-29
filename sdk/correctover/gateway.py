# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover v4.4.2 — Gateway Proxy Server.

OpenAI-compatible API gateway with MAPE-K self-healing.
Drop-in replacement for OpenAI API endpoint — any client can use it.

Usage:
    from correctover.gateway import serve
    serve(host="127.0.0.1", port=8080)

Or CLI:
    python -m correctover.gateway --port 8080

Environment variables:
    CORRECTOVER_PROVIDERS=openai,anthropic,deepseek
    OPENAI_API_KEY=sk-...
    ANTHROPIC_API_KEY=sk-ant-...
    DEEPSEEK_API_KEY=sk-...
"""

import os
import sys
import json
import time
import asyncio
import hashlib
import hmac
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any

from ._engine import (
    SelfHealingEngine, ProviderConfig, CallResult, Contract, SemanticDomain,
    MapeKPhase, MapeKTrace, FaultCategory, __version__,
    _PRESET_URLS, _ENV_KEY_MAP, _MODEL_PROVIDERS, _DEFAULT_MODELS,
)


class GatewayConfig:
    """Gateway server configuration."""
    def __init__(self):
        self.host = os.environ.get("CORRECTOVER_HOST", "127.0.0.1")
        self.port = int(os.environ.get("CORRECTOVER_PORT", "8080"))
        self.providers = os.environ.get("CORRECTOVER_PROVIDERS", "").split(",")
        self.api_keys: Dict[str, str] = {}
        self.max_request_size = 10 * 1024 * 1024  # 10MB
        self.enable_streaming = True
        self.enable_metrics = True
        self.enable_health = True
        self.cors_enabled = True
        self.enable_dashboard = os.environ.get("CORRECTOVER_ENABLE_DASHBOARD", "0") == "1"
        self.auth_token = os.environ.get("CORRECTOVER_AUTH_TOKEN", "")  # Optional gateway auth

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        cfg = cls()
        # Parse API keys from env
        for name, env_var in _ENV_KEY_MAP.items():
            key = os.environ.get(env_var, "")
            if key:
                cfg.api_keys[name] = key
        return cfg


def _create_engine(config: GatewayConfig) -> SelfHealingEngine:
    """Create engine from gateway config."""
    providers = [p.strip() for p in config.providers if p.strip()]
    if not providers:
        # Auto-discover from available keys
        providers = [name for name, env_var in _ENV_KEY_MAP.items()
                     if os.environ.get(env_var, "")]
    if not providers:
        providers = ["openai"]  # fallback

    return SelfHealingEngine(providers=providers, api_keys=config.api_keys)


class _GatewayHandler(BaseHTTPRequestHandler):
    """HTTP handler for OpenAI-compatible API gateway."""

    # Instance-level references set via serve() — using class vars for HTTPServer compatibility
    engine: SelfHealingEngine = None  # type: ignore
    config: GatewayConfig = None  # type: ignore

    def log_message(self, format, *args):
        """Suppress default logging, use structured format."""
        pass

    def _check_auth(self) -> bool:
        """Check gateway authentication if configured."""
        if not self.config.auth_token:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return hmac.compare_digest(auth[7:], self.config.auth_token)
        return False

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str, error_type: str = "server_error"):
        self._send_json({
            "error": {
                "message": message,
                "type": error_type,
                "code": status,
            }
        }, status)

    def _send_sse_chunk(self, data: Dict):
        """Send a Server-Sent Events chunk."""
        chunk = f"data: {json.dumps(data)}\n\n"
        self.wfile.write(chunk.encode("utf-8"))
        self.wfile.flush()

    def _send_sse_done(self):
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _set_cors_headers(self):
        if self.config.cors_enabled:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")

    # ── Route handlers ──

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        if not self._check_auth():
            self._send_error(401, "Unauthorized", "authentication_error")
            return

        path = self.path.split("?")[0]

        if path == "/v1/models":
            self._handle_list_models()
        elif path == "/v1/models/" :
            self._handle_list_models()
        elif path.startswith("/v1/models/"):
            model_id = path[len("/v1/models/"):]
            self._handle_get_model(model_id)
        elif path == "/health":
            self._handle_health()
        elif path == "/metrics":
            self._handle_metrics()
        elif path == "/stats":
            self._handle_stats()
        elif path == "/mapek":
            self._handle_mapek()
        elif path == "/providers":
            self._handle_providers()
        elif path == "/":
            self._handle_dashboard()
        else:
            self._send_error(404, f"Not found: {path}")

    def do_POST(self):
        if not self._check_auth():
            self._send_error(401, "Unauthorized", "authentication_error")
            return

        path = self.path.split("?")[0]

        if path == "/v1/chat/completions":
            self._handle_chat_completions()
        elif path == "/v1/completions":
            self._handle_completions()
        elif path == "/v1/embeddings":
            self._handle_embeddings()
        else:
            self._send_error(404, f"Not found: {path}")

    # ── API endpoints ──

    def _handle_chat_completions(self):
        """POST /v1/chat/completions — OpenAI-compatible chat endpoint."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > self.config.max_request_size:
                self._send_error(413, "Request too large")
                return
            body = self.rfile.read(content_length)
            req = json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self._send_error(400, f"Invalid JSON: {e}", "invalid_request_error")
            return

        # Extract parameters
        messages = req.get("messages", [])
        model = req.get("model", "")
        stream = req.get("stream", False) and self.config.enable_streaming
        temperature = req.get("temperature")
        max_tokens = req.get("max_tokens")
        top_p = req.get("top_p")

        # Build prompt from messages
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multimodal content
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                content = " ".join(text_parts)
            prompt_parts.append(f"{role}: {content}")
        prompt = "\n".join(prompt_parts)

        # Determine semantic domain from request
        has_schema = bool(req.get("response_format") or req.get("functions"))
        task_type = req.get("task_type", "")

        # Build contract if structured output requested
        contract = None
        response_format = req.get("response_format")
        if response_format and isinstance(response_format, dict):
            schema = response_format.get("json_schema", response_format.get("schema"))
            if schema:
                contract = Contract(output_schema=schema)

        # Execute via engine
        kwargs: Dict[str, Any] = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if top_p is not None:
            kwargs["top_p"] = top_p

        try:
            result = self.engine.call_sync(
                prompt=prompt, model=model,
                task_type=task_type, has_schema=has_schema,
                contract=contract, **kwargs
            )
        except Exception as e:
            error_msg = str(e)[:500]
            error_type = type(e).__name__
            self._send_error(502, f"Upstream error: {error_msg}", error_type)
            return

        if stream:
            self._send_stream_response(result, model)
        else:
            self._send_chat_response(result, model)

    def _handle_completions(self):
        """POST /v1/completions — Legacy completions endpoint."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > self.config.max_request_size:
                self._send_error(413, "Request too large")
                return
            body = self.rfile.read(content_length)
            req = json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self._send_error(400, f"Invalid JSON: {e}", "invalid_request_error")
            return

        prompt = req.get("prompt", "")
        model = req.get("model", "")

        try:
            result = self.engine.call_sync(prompt=prompt, model=model)
        except Exception as e:
            self._send_error(502, f"Upstream error: {str(e)[:500]}")
            return

        # Extract token usage from upstream response if available
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if result.raw_response and isinstance(result.raw_response, dict):
            upstream_usage = result.raw_response.get("usage")
            if upstream_usage:
                usage = {
                    "prompt_tokens": upstream_usage.get("prompt_tokens", 0),
                    "completion_tokens": upstream_usage.get("completion_tokens", 0),
                    "total_tokens": upstream_usage.get("total_tokens", 0),
                }

        response = {
            "id": f"cmpl-{int(time.time())}",
            "object": "text_completion",
            "created": int(time.time()),
            "model": result.model,
            "choices": [{
                "text": result.text,
                "index": 0,
                "finish_reason": "stop",
            }],
            "usage": usage,
        }
        if result.mapek_trace:
            response["_correctover"] = {
                "provider": result.provider,
                "heal_level": result.heal_level,
                "semantic_domain": result.semantic_domain,
                "validation_passed": result.validation_passed,
                "mapek_trace": result.mapek_trace,
            }
        self._send_json(response)

    def _handle_embeddings(self):
        """POST /v1/embeddings — Embeddings endpoint.
        Proxies to upstream embedding API via engine with api_type='embeddings'.
        """
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > self.config.max_request_size:
                self._send_error(413, "Request too large")
                return
            body = self.rfile.read(content_length)
            req = json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self._send_error(400, f"Invalid JSON: {e}", "invalid_request_error")
            return

        input_text = req.get("input", "")
        model = req.get("model", "")

        try:
            # Use the engine's raw execute to call embedding endpoint directly
            result = self.engine.call_sync(
                prompt=str(input_text), model=model,
                task_type="extraction", has_schema=True,
                api_type="embeddings",
            )
        except Exception as e:
            self._send_error(502, f"Upstream error: {str(e)[:500]}")
            return

        # result.text for embeddings should be a list of floats (from _execute)
        embedding_data = result.text
        if isinstance(embedding_data, str):
            # If we got text instead of a float list, the upstream doesn't support
            # embedding or returned an unexpected format
            self._send_error(502, "Upstream provider did not return valid embedding data")
            return

        response = {
            "object": "list",
            "data": [{"object": "embedding", "embedding": embedding_data, "index": 0}],
            "model": result.model,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }
        self._send_json(response)

    def _handle_list_models(self):
        """GET /v1/models — List available models."""
        models = []
        for provider, model_list in _MODEL_PROVIDERS.items():
            for m in model_list:
                models.append({
                    "id": m,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": provider,
                })
        self._send_json({"object": "list", "data": models})

    def _handle_get_model(self, model_id: str):
        """GET /v1/models/{model_id} — Get model details."""
        for provider, model_list in _MODEL_PROVIDERS.items():
            if model_id in model_list:
                self._send_json({
                    "id": model_id,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": provider,
                })
                return
        self._send_error(404, f"Model not found: {model_id}", "model_not_found")

    def _handle_health(self):
        """GET /health — Kubernetes liveness/readiness probe."""
        health = self.engine.get_metrics().health_endpoint()
        health["providers"] = self.engine.health_check()
        self._send_json(health)

    def _handle_metrics(self):
        """GET /metrics — Prometheus metrics."""
        metrics_text = self.engine.get_metrics().prometheus_format()
        body = metrics_text.encode("utf-8")
        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_stats(self):
        """GET /stats — Full engine stats."""
        self._send_json(self.engine.get_stats())

    def _handle_mapek(self):
        """GET /mapek — MAPE-K loop statistics."""
        self._send_json(self.engine.get_mapek_stats())

    def _handle_providers(self):
        """GET /providers — Provider health and status."""
        result = {}
        for name, cfg in self.engine._providers.items():
            result[name] = cfg.to_dict()
        self._send_json(result)

    def _handle_dashboard(self):
        """GET / — Built-in monitoring dashboard. Disabled by default for security."""
        if not self.config.enable_dashboard:
            self._send_error(404, "Dashboard disabled. Set CORRECTOVER_ENABLE_DASHBOARD=1 to enable.")
            return

        stats = self.engine.get_stats()
        mapek = self.engine.get_mapek_stats()

        # Build provider cards
        provider_cards = ""
        for name, p in stats.get("providers", {}).items():
            color = "#4caf50" if p.get("healthy") else "#f44336"
            provider_cards += (
                f'<div class="card"><span class="dot" style="background:{color}"></span>'
                f'<b>{name}</b><br>'
                f'<small>Score: {p.get("health_score","?")} | '
                f'{p.get("avg_latency_ms","?")}ms</small><br>'
                f'<small>&#10003;{p.get("success",0)} &#10007;{p.get("fail",0)} '
                f'CB:{p.get("circuit",{}).get("state","?")}</small></div>'
            )

        # Build metrics section
        metrics_rows = ""
        for k, v in stats.get("metrics", {}).get("counters", {}).items():
            if any(x in k for x in ["calls", "heal", "fault", "error", "success", "contract"]):
                metrics_rows += f'<div class="metric"><b>{k}</b>: {v}</div>'

        # Build MAPE-K section
        cascade = mapek.get("heal_cascade", {})
        boundaries = mapek.get("semantic_boundaries", {})
        contract_stats = mapek.get("contract_validation", {})

        html = f"""<!DOCTYPE html>
<html><head><title>Correctover Gateway v{stats['version']}</title>
<meta http-equiv="refresh" content="5">
<style>
  :root {{ --bg: #11111b; --card: #1e1e2e; --text: #cdd6f4; --accent: #89b4fa;
           --green: #a6e3a1; --red: #f38ba8; --yellow: #f9e2af; --purple: #cba6f7; }}
  body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; margin: 20px; }}
  h1 {{ color: var(--accent); }} h2 {{ color: var(--purple); }}
  a {{ color: var(--accent); }}
  .card {{ display: inline-block; margin: 8px; padding: 12px; border-radius: 8px;
           background: var(--card); min-width: 180px; }}
  .dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 6px; }}
  .metric {{ padding: 4px 0; }}
  .metric b {{ color: var(--accent); }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .section {{ background: var(--card); padding: 16px; border-radius: 8px; margin-bottom: 16px; }}
  .phase {{ display: inline-block; padding: 4px 12px; margin: 2px; border-radius: 4px;
            background: var(--card); border: 1px solid var(--accent); color: var(--accent); font-size: 14px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin: 2px; }}
  .badge-green {{ background: #1b4332; color: var(--green); }}
  .badge-red {{ background: #3c1321; color: var(--red); }}
  .badge-yellow {{ background: #3c2f12; color: var(--yellow); }}
</style></head>
<body>
<h1>Correctover Gateway v{stats['version']}</h1>

<h2>MAPE-K Loop</h2>
<div class="section">
  <span class="phase">Monitor</span> →
  <span class="phase">Analyze</span> →
  <span class="phase">Plan</span> →
  <span class="phase">Execute</span> →
  <span class="phase">Knowledge</span>
  <p style="margin-top:12px;color:#a6adc8">
    Every call traverses all 5 phases. Total calls: <b>{stats['call_count']}</b> |
    Healed: <b style="color:var(--green)">{stats['heal_count']}</b> ({stats['heal_rate']})
  </p>
</div>

<h2>Providers</h2>
<div class="section">{provider_cards}</div>

<h2>Heal Cascade</h2>
<div class="section grid">
  <div>
    <span class="badge badge-green">L1 Retry</span> {cascade.get('l1_retry',0)}<br>
    <span class="badge badge-yellow">L2 Downgrade</span> {cascade.get('l2_downgrade',0)}<br>
    <span class="badge badge-red">L3 Failover</span> {cascade.get('l3_failover',0)}<br>
    <span class="badge badge-green">L4 Learned</span> {cascade.get('l4_learned',0)}
  </div>
  <div>
    <b style="color:var(--yellow)">Contract Validation</b><br>
    Failed (STRONG_EQUIV): <span style="color:var(--red)">{contract_stats.get('failed_strong_equiv',0)}</span><br>
    Warning (TAU): <span style="color:var(--yellow)">{contract_stats.get('warning_tau_domain',0)}</span><br><br>
    <b style="color:var(--purple)">Semantic Boundaries</b><br>
    Downgrade blocked (OOB): {boundaries.get('downgrade_blocked_oob',0)}<br>
    Drift fail-loud: {boundaries.get('drift_fail_loud',0)}
  </div>
</div>

<h2>Live Metrics</h2>
<div class="section">{metrics_rows}</div>

<p style="color:#585b70;margin-top:20px">
  Auto-refresh 5s |
  <a href="/metrics">Prometheus</a> |
  <a href="/health">Health</a> |
  <a href="/stats">Stats JSON</a> |
  <a href="/mapek">MAPE-K Stats</a> |
  <a href="/providers">Providers</a> |
  <a href="/v1/models">Models</a>
</p>
</body></html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Response formatters ──

    def _send_chat_response(self, result: CallResult, requested_model: str):
        """Send OpenAI-format chat completion response."""
        # Extract token usage from upstream response if available
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if result.raw_response and isinstance(result.raw_response, dict):
            upstream_usage = result.raw_response.get("usage")
            if upstream_usage:
                usage = {
                    "prompt_tokens": upstream_usage.get("prompt_tokens", 0),
                    "completion_tokens": upstream_usage.get("completion_tokens", 0),
                    "total_tokens": upstream_usage.get("total_tokens", 0),
                }

        response = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": result.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": result.text},
                "finish_reason": "stop",
            }],
            "usage": usage,
        }
        # Attach Correctover metadata
        nb_meta = {}
        if result.provider != result.original_provider:
            nb_meta["failover"] = f"{result.original_provider} → {result.provider}"
        if result.heal_level:
            nb_meta["heal_level"] = result.heal_level
        if result.semantic_domain:
            nb_meta["semantic_domain"] = result.semantic_domain
        if result.validation_passed is not None:
            nb_meta["validation_passed"] = result.validation_passed
        if result.mapek_trace:
            nb_meta["mapek_trace"] = result.mapek_trace
        if result.contract_result:
            nb_meta["contract_result"] = result.contract_result
        if nb_meta:
            response["_correctover"] = nb_meta

        self._send_json(response)

    def _send_stream_response(self, result: CallResult, requested_model: str):
        """Send SSE stream response (simulated from non-streaming result)."""
        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        # Send content chunk
        chunk = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": result.model,
            "choices": [{
                "index": 0,
                "delta": {"content": result.text},
                "finish_reason": None,
            }],
        }
        self._send_sse_chunk(chunk)

        # Send finish chunk
        finish_chunk = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": result.model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        self._send_sse_chunk(finish_chunk)

        # Send Correctover metadata
        if result.mapek_trace or result.heal_level:
            meta_chunk = {
                "_correctover": {
                    "heal_level": result.heal_level,
                    "semantic_domain": result.semantic_domain,
                    "validation_passed": result.validation_passed,
                    "mapek_trace": result.mapek_trace,
                }
            }
            self._send_sse_chunk(meta_chunk)

        self._send_sse_done()


def serve(host: str = "127.0.0.1", port: int = 8080,
          providers: list = None, api_keys: Dict[str, str] = None,
          auth_token: str = "", config: GatewayConfig = None) -> HTTPServer:
    """Start the Correctover Gateway server.

    This is an OpenAI-compatible API proxy with MAPE-K self-healing.
    Any OpenAI client can connect to it as a drop-in replacement.

    Args:
        host: Bind address (default: 0.0.0.0)
        port: Bind port (default: 8080)
        providers: List of provider names (e.g. ["openai", "anthropic"])
        api_keys: Dict of provider API keys
        auth_token: Optional gateway authentication token
        config: Full GatewayConfig (overrides other params)

    Returns:
        HTTPServer instance (runs in background thread)

    Example:
        server = serve(port=8080, providers=["openai", "deepseek"])
        # Now any OpenAI client can use http://localhost:8080/v1/chat/completions
    """
    if config is None:
        config = GatewayConfig()
    if host:
        config.host = host
    if port:
        config.port = port
    if providers:
        config.providers = providers
    if api_keys:
        config.api_keys.update(api_keys)
    if auth_token:
        config.auth_token = auth_token

    # Create engine
    engine = _create_engine(config)

    # Inject engine into handler class
    _GatewayHandler.engine = engine
    _GatewayHandler.config = config

    # Start server
    server = HTTPServer((config.host, config.port), _GatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"""
  ╔══════════════════════════════════════════════════════╗
  ║  Correctover Gateway v{__version__}                    ║
  ║  MAPE-K Self-Healing API Proxy                       ║
  ╚══════════════════════════════════════════════════════╝

  Gateway:     http://{config.host}:{config.port}/
  Chat API:    http://{config.host}:{config.port}/v1/chat/completions
  Models:      http://{config.host}:{config.port}/v1/models
  Health:      http://{config.host}:{config.port}/health
  Prometheus:  http://{config.host}:{config.port}/metrics
  MAPE-K:      http://{config.host}:{config.port}/mapek

  Providers:   {', '.join(engine.get_available_providers()) or 'none'}
  Dashboard:   http://{config.host}:{config.port}/

  Compatible with: OpenAI Python SDK, curl, any HTTP client
""")

    return server


def main():
    """CLI entry point for gateway server."""
    import argparse
    parser = argparse.ArgumentParser(description="Correctover Gateway Server")
    parser.add_argument("--host", default=os.environ.get("CORRECTOVER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CORRECTOVER_PORT", "8080")))
    parser.add_argument("--providers", default=os.environ.get("CORRECTOVER_PROVIDERS", ""),
                        help="Comma-separated provider names")
    parser.add_argument("--auth-token", default=os.environ.get("CORRECTOVER_AUTH_TOKEN", ""),
                        help="Gateway authentication token")
    args = parser.parse_args()

    providers = [p.strip() for p in args.providers.split(",") if p.strip()] if args.providers else None

    server = serve(
        host=args.host,
        port=args.port,
        providers=providers,
        auth_token=args.auth_token,
    )

    try:
        # Keep main thread alive
        while True:
            import time as _time
            _time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down Correctover Gateway...")
        server.shutdown()


if __name__ == "__main__":
    main()
