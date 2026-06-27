    },
    "portkey": {
        "name": "Rohit",
        "full_name": "Rohit Agarwal",
        "email": "rohit@portkey.ai",
        "company": "Portkey AI",
        "subject": "Correctover x Portkey: Verified failover as a complement to AI gateway observability",
        "body": """Hi Rohit,

Portkey's observability-first approach to AI gateways is impressive — the control plane view is exactly what teams need as they scale.

I'm building Correctover at a complementary layer: verified failover.

Where Portkey excels at monitoring and managing provider traffic, Correctover adds contract validation before accepting any failover response. It checks structure, schema, latency, cost, identity, and integrity — not just HTTP 200.

The interesting part: Correctover is an embedded SDK (not a proxy), so it can layer on top of Portkey's gateway without data interception or architecture conflicts. Your users get Portkey's observability AND verified failover.

Would you be open to a quick call? I think there's a natural integration play here.

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "openrouter": {
        "name": "Alex",
        "full_name": "Alex Atallah",
        "email": "alex@openrouter.ai",
        "company": "OpenRouter",
        "subject": "Beyond provider routing — verified failover for OpenRouter users",
        "body": """Hi Alex,

OpenRouter's provider routing has made multi-LLM access simple for thousands of developers. As you scale, I imagine response quality consistency across providers is becoming a harder problem.

I'm building Correctover — an embedded SDK for verified failover.

The core problem we solve: when a request fails over to a backup provider, current gateways accept the response on HTTP 200 alone. Correctover validates it across 6 dimensions before accepting (structure, schema, latency, cost, identity, integrity).

From OpenRouter's perspective, this could be a value-add layer — your users already route through OpenRouter; Correctover ensures the routed response is actually correct.

Happy to share benchmarks (P50 diagnosis: 22µs, zero additional API latency). Open for a brief chat?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "langchain": {
        "name": "Harrison",
        "full_name": "Harrison Chase",
        "email": "harrison@langchain.dev",
        "company": "LangChain",
        "subject": "Verified failover for LangChain applications — a reliability layer for multi-provider chains",
        "body": """Hi Harrison,

LangChain has become the standard framework for LLM application development. As your users move from prototyping to production, provider reliability is becoming a critical concern — especially in multi-provider chains where a single silent failure cascades.

I'm building Correctover — an embedded SDK for verified LLM API failover.

It layers onto existing LangChain applications without architecture changes: Correctover wraps your LLM client and validates every failover response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it.

The result: LangChain apps get verified failover without rewriting routing logic. Particularly valuable for chains that span multiple providers where a silent failure in one link breaks the whole pipeline.

Would you be open to a brief conversation about how this could fit the LangChain ecosystem?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "llamaindex": {
        "name": "Jerry",
        "full_name": "Jerry Liu",
        "email": "jerry@llamaindex.ai",
        "company": "LlamaIndex",
        "subject": "Reliable multi-provider RAG — verified failover for LlamaIndex pipelines",
        "body": """Hi Jerry,

LlamaIndex's data framework has made RAG accessible to a huge developer audience. As RAG pipelines grow more complex with multi-provider strategies, the reliability of each LLM call in the pipeline becomes critical.

I'm building Correctover — an embedded SDK for verified LLM API failover.

For LlamaIndex users running production RAG pipelines, Correctover adds contract validation before accepting any failover response: structure, schema, latency, cost, identity, and integrity checks. If a backup provider returns a wrong response, Correctover catches it before it reaches the pipeline.

It's a one-line integration, zero network overhead, and works with any provider.

I'd love to explore how this could benefit LlamaIndex's production users. Open for a quick call?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
}
