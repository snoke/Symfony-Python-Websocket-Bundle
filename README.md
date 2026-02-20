Symfony + Python Realtime Stack — Branch Overview

Realtime in Symfony is simple for small apps, but scaling bidirectional WebSockets introduces challenges:
• Booting full Symfony per WebSocket message is inefficient at high connection counts
• SSE (e.g., Mercure) is not true bidirectional communication
• Stateless transport, presence tracking, and GDPR‑compliant retention require infrastructure control

This stack keeps Symfony at the core while offloading realtime concerns to specialized layers.

---

1) terminator (Symfony‑first) — Symfony stays in charge

Think of Terminator as incremental realtime for your existing app:
• WebSocket gateway + webhook/HTTP presence
• Quick integration into any Symfony app
• Ideal for moderate realtime workloads
• Symfony remains fully in control: Event Dispatcher, DI, Security Guards stay untouched
• True client↔server communication (not just SSE)
• Business logic stays fully testable; gateway can be mocked

Strategic fit:
• Classic apps with moderate realtime load
• Production‑ready, not a toy
• Add realtime without restructuring your app

---

2) realtime-core (Broker‑first) — scale without limits

For high‑load or self‑hosted realtime, Realtime‑Core separates transport from application logic:
• No webhook; events flow exclusively through a broker (Redis/RabbitMQ)
• Gateway is stateless; presence stored in Redis
• Handles high connection counts efficiently (no Symfony boot per message)
• Symfony remains the producer/consumer; core logic untouched
• Full control over retention, TTL, and GDPR compliance
• Testable: broker/gateway can be mocked; Symfony core fully unit‑testable

Strategic fit:
• High‑scale, self‑hosted production systems
• True separation of concerns: transport vs. application
• Fully Symfony‑compatible — not anti‑Symfony

---

Key takeaways
• Symfony remains the heart of your app in both models
• Terminator = fast integration, moderate scale, fully Symfony‑native
• Realtime‑Core = stateless transport, scalable to high loads, infrastructure control
• Choose based on scaling needs and operational requirements
• Both branches provide production‑ready, bidirectional WebSockets

---

Start
- `git checkout terminator`
- `git checkout realtime-core`

Each branch contains its own README with setup and demo steps.
