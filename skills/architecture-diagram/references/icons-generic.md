# Generic Icon Catalog

For `provider: generic` nodes, or any component with no cloud-provider equivalent (on-prem servers, Kubernetes internals, generic databases/queues/users). Cloud provider icons come from `references/services-aws.yaml`, `services-azure.yaml`, and `services-gcp.yaml` instead — those are real vendor icon geometry, not this hand-drawn set.

All icons: `viewBox="0 0 64 64"`, render at 44×44px default. Stroke `currentColor`, `stroke-width="2.5"` primary shapes. Fill `currentColor` with `fill-opacity` 0.08–0.2 for enclosed shapes.

Use the slug below each heading as the node's `service` value with `provider: generic` (or set `provider: generic` at the top level and omit it per node). `engine/icons.py` resolves it through `assets/generic-icons.json` — no network fetch, no cache directory, always available. A generic-provider node with no `service` set (or an unrecognized slug) still renders cleanly as a labeled colored placeholder; reach for a specific glyph here when it adds real clarity over that placeholder.

## Catalog

### Server / Compute

`service: server-compute`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="10" y="6" width="44" height="16" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><rect x="10" y="24" width="44" height="16" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><rect x="10" y="42" width="44" height="16" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><circle cx="18" cy="14" r="2.5" fill="currentColor"/><circle cx="18" cy="32" r="2.5" fill="currentColor"/><circle cx="18" cy="50" r="2.5" fill="currentColor"/><line x1="36" y1="12" x2="48" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="36" y1="16" x2="44" y2="16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
```

### Database

`service: database`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><ellipse cx="32" cy="14" rx="20" ry="8" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><path d="M12 14v36c0 4.4 9 8 20 8s20-3.6 20-8V14" stroke="currentColor" stroke-width="2.5"/><path d="M12 26c0 4.4 9 8 20 8s20-3.6 20-8" stroke="currentColor" stroke-width="2" stroke-opacity="0.5"/><path d="M12 38c0 4.4 9 8 20 8s20-3.6 20-8" stroke="currentColor" stroke-width="2" stroke-opacity="0.5"/></svg>
```

### Container

`service: container`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="8" y="14" width="48" height="36" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><rect x="14" y="20" width="16" height="12" rx="2" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/><rect x="34" y="20" width="16" height="12" rx="2" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/><rect x="14" y="35" width="16" height="9" rx="2" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/><rect x="34" y="35" width="16" height="9" rx="2" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/></svg>
```

### Kubernetes

`service: kubernetes`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="22" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><circle cx="32" cy="32" r="6" fill="currentColor"/><line x1="32" y1="12" x2="32" y2="24" stroke="currentColor" stroke-width="2.5"/><line x1="32" y1="40" x2="32" y2="52" stroke="currentColor" stroke-width="2.5"/><line x1="14" y1="22" x2="24" y2="28" stroke="currentColor" stroke-width="2.5"/><line x1="40" y1="36" x2="50" y2="42" stroke="currentColor" stroke-width="2.5"/><line x1="14" y1="42" x2="24" y2="36" stroke="currentColor" stroke-width="2.5"/><line x1="40" y1="28" x2="50" y2="22" stroke="currentColor" stroke-width="2.5"/><circle cx="32" cy="12" r="3" fill="currentColor"/><circle cx="32" cy="52" r="3" fill="currentColor"/><circle cx="14" cy="22" r="3" fill="currentColor"/><circle cx="50" cy="42" r="3" fill="currentColor"/><circle cx="14" cy="42" r="3" fill="currentColor"/><circle cx="50" cy="22" r="3" fill="currentColor"/></svg>
```

### Load Balancer

`service: load-balancer`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="16" r="10" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><path d="M32 26 L16 48 M32 26 L32 48 M32 26 L48 48" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><circle cx="16" cy="50" r="5" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/><circle cx="32" cy="50" r="5" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/><circle cx="48" cy="50" r="5" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/></svg>
```

### Queue / Message Bus

`service: queue-message-bus`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="6" y="22" width="12" height="20" rx="2" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.2"/><rect x="20" y="22" width="12" height="20" rx="2" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.15"/><rect x="34" y="22" width="12" height="20" rx="2" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><path d="M50 32 L58 32 M55 28 L59 32 L55 36" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
```

### Function / Serverless (lightning bolt)

`service: function-serverless`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M20 8 L44 8 L38 32 L48 32 L24 58 L30 36 L18 36 Z" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round" fill="currentColor" fill-opacity="0.15"/></svg>
```

### Object Storage (hexagonal prism)

`service: object-storage`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M14 18 L32 8 L50 18 L50 46 L32 56 L14 46 Z" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round" fill="currentColor" fill-opacity="0.1"/><path d="M14 18 L32 28 L50 18" stroke="currentColor" stroke-width="2" stroke-opacity="0.5"/><line x1="32" y1="28" x2="32" y2="56" stroke="currentColor" stroke-width="2" stroke-opacity="0.5"/></svg>
```

### Network / Globe

`service: network-globe`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="24" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.06"/><ellipse cx="32" cy="32" rx="12" ry="24" stroke="currentColor" stroke-width="1.8"/><line x1="8" y1="22" x2="56" y2="22" stroke="currentColor" stroke-width="1.5"/><line x1="8" y1="42" x2="56" y2="42" stroke="currentColor" stroke-width="1.5"/></svg>
```

### Firewall / Shield

`service: firewall-shield`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M32 6 L52 16 L52 34 C52 46 42 54 32 58 C22 54 12 46 12 34 L12 16 Z" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round" fill="currentColor" fill-opacity="0.1"/><path d="M26 32 L30 36 L38 28" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>
```

### API Gateway

`service: api-gateway`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="24" y="6" width="16" height="52" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><path d="M8 20 L24 20 M8 32 L24 32 M8 44 L24 44" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M40 26 L56 26 M40 38 L56 38" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="8" cy="20" r="3" fill="currentColor" fill-opacity="0.3"/><circle cx="8" cy="32" r="3" fill="currentColor" fill-opacity="0.3"/><circle cx="8" cy="44" r="3" fill="currentColor" fill-opacity="0.3"/></svg>
```

### Monitoring / Chart

`service: monitoring-chart`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="8" y="10" width="48" height="36" rx="4" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><polyline points="14,36 22,28 28,34 36,18 42,30 50,22" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/><line x1="24" y1="52" x2="40" y2="52" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><line x1="32" y1="46" x2="32" y2="52" stroke="currentColor" stroke-width="2.5"/></svg>
```

### Notification / Bell

`service: notification-bell`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M24 46 C24 50 28 54 32 54 C36 54 40 50 40 46" stroke="currentColor" stroke-width="2.5"/><path d="M16 46 L48 46 L44 38 C42 30 42 24 42 20 C42 14 38 8 32 8 C26 8 22 14 22 20 C22 24 22 30 20 38 Z" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/></svg>
```

### Logging / Document

`service: logging-document`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="14" y="6" width="36" height="52" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><line x1="22" y1="18" x2="42" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="22" y1="26" x2="38" y2="26" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="22" y1="34" x2="42" y2="34" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="22" y1="42" x2="34" y2="42" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="22" y1="50" x2="40" y2="50" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
```

### Streaming (waves)

`service: streaming`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M6 22 Q20 12, 32 22 Q44 32, 58 22" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" fill="none"/><path d="M6 32 Q20 22, 32 32 Q44 42, 58 32" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" fill="none"/><path d="M6 42 Q20 32, 32 42 Q44 52, 58 42" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" fill="none"/></svg>
```

### Cloud (generic)

`service: cloud`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M18 48 C10 48 4 42 4 34 C4 26 10 20 18 20 C18 12 24 6 34 6 C42 6 48 10 50 18 C56 18 60 24 60 30 C60 38 54 44 46 44 L46 48 Z" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/></svg>
```

### User / Person

`service: user-person`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="18" r="12" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><path d="M10 56 C10 42 20 34 32 34 C44 34 54 42 54 56" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/></svg>
```

### People / Group

`service: people-group`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="24" cy="16" r="10" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><path d="M6 50 C6 38 14 32 24 32 C34 32 42 38 42 50" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.06"/><circle cx="42" cy="18" r="8" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.1"/><path d="M30 52 C30 42 36 36 42 36 C50 36 56 42 56 52" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.06"/></svg>
```

### Mobile Device

`service: mobile-device`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="18" y="4" width="28" height="56" rx="4" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><line x1="18" y1="14" x2="46" y2="14" stroke="currentColor" stroke-width="2"/><line x1="18" y1="48" x2="46" y2="48" stroke="currentColor" stroke-width="2"/><circle cx="32" cy="54" r="3" fill="currentColor" fill-opacity="0.3"/></svg>
```

### Browser / Desktop

`service: browser-desktop`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="6" y="6" width="52" height="38" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><line x1="6" y1="16" x2="58" y2="16" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="11" r="2" fill="currentColor" fill-opacity="0.4"/><circle cx="18" cy="11" r="2" fill="currentColor" fill-opacity="0.4"/><circle cx="24" cy="11" r="2" fill="currentColor" fill-opacity="0.4"/><line x1="24" y1="48" x2="40" y2="48" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><line x1="20" y1="54" x2="44" y2="54" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg>
```

### Integration / Connector (hub with spokes)

`service: integration-connector`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="16" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><circle cx="32" cy="32" r="5" fill="currentColor"/><path d="M20 32 L28 32 M36 32 L44 32 M32 20 L32 28 M32 36 L32 44" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><path d="M8 32 L16 32 M48 32 L56 32 M32 8 L32 16 M32 48 L32 56" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
```

### Key / Lock / Security

`service: key-lock-security`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="14" y="28" width="36" height="28" rx="4" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.12"/><path d="M22 28 V20 C22 12 26 8 32 8 C38 8 42 12 42 20 V28" stroke="currentColor" stroke-width="2.5" fill="none"/><circle cx="32" cy="40" r="4" fill="currentColor"/><line x1="32" y1="44" x2="32" y2="50" stroke="currentColor" stroke-width="2.5"/></svg>
```

### Building / Enterprise

`service: building-enterprise`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="12" y="10" width="40" height="48" rx="2" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><rect x="20" y="18" width="8" height="6" rx="1" stroke="currentColor" stroke-width="1.5" fill="currentColor" fill-opacity="0.15"/><rect x="36" y="18" width="8" height="6" rx="1" stroke="currentColor" stroke-width="1.5" fill="currentColor" fill-opacity="0.15"/><rect x="20" y="30" width="8" height="6" rx="1" stroke="currentColor" stroke-width="1.5" fill="currentColor" fill-opacity="0.15"/><rect x="36" y="30" width="8" height="6" rx="1" stroke="currentColor" stroke-width="1.5" fill="currentColor" fill-opacity="0.15"/><rect x="26" y="44" width="12" height="14" rx="1" stroke="currentColor" stroke-width="1.5" fill="currentColor" fill-opacity="0.2"/></svg>
```

### Bank / Financial

`service: bank-financial`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 22 L32 8 L56 22 Z" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><line x1="8" y1="22" x2="56" y2="22" stroke="currentColor" stroke-width="2.5"/><rect x="14" y="24" width="6" height="22" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.08"/><rect x="24" y="24" width="6" height="22" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.08"/><rect x="34" y="24" width="6" height="22" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.08"/><rect x="44" y="24" width="6" height="22" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.08"/><rect x="8" y="46" width="48" height="6" rx="1" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.12"/></svg>
```

### Medical Cross / Health

`service: medical-cross-health`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="8" y="8" width="48" height="48" rx="8" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><rect x="26" y="16" width="12" height="32" rx="2" fill="currentColor" fill-opacity="0.3"/><rect x="16" y="26" width="32" height="12" rx="2" fill="currentColor" fill-opacity="0.3"/></svg>
```

### Warning / Triangle

`service: warning-triangle`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M32 6 L58 54 L6 54 Z" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round" fill="currentColor" fill-opacity="0.08"/><line x1="32" y1="24" x2="32" y2="38" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><circle cx="32" cy="46" r="2.5" fill="currentColor"/></svg>
```

### Gear / Settings

`service: gear-settings`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="10" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><path d="M30 6 L34 6 L35 14 L29 14 Z M30 50 L34 50 L35 58 L29 58 Z M6 30 L6 34 L14 35 L14 29 Z M50 30 L50 34 L58 35 L58 29 Z M13 13 L16 16 L22 12 L18 8 Z M48 48 L44 44 L42 52 L46 56 Z M48 16 L44 12 L42 18 L46 22 Z M16 48 L18 56 L22 52 L20 44 Z" fill="currentColor" fill-opacity="0.6"/></svg>
```

### Home / House

`service: home-house`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 30 L32 10 L56 30" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M14 28 L14 54 L50 54 L50 28" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><rect x="26" y="38" width="12" height="16" rx="1" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.15"/></svg>
```

### Pin / Location

`service: pin-location`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M32 58 C32 58 50 38 50 24 C50 14 42 6 32 6 C22 6 14 14 14 24 C14 38 32 58 32 58 Z" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.12"/><circle cx="32" cy="24" r="8" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.2"/></svg>
```

### Exclamation / Alert

`service: exclamation-alert`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="10" y="6" width="44" height="52" rx="6" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><line x1="32" y1="18" x2="32" y2="36" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/><circle cx="32" cy="46" r="3" fill="currentColor"/></svg>
```

### Workflow / Process (3 connected circles)

`service: workflow-process`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="14" r="8" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.15"/><circle cx="50" cy="14" r="8" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.15"/><circle cx="32" cy="50" r="8" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.15"/><path d="M22 16 L42 16 M46 22 L36 42 M18 22 L28 42" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
```

### Middleware / Stack

`service: middleware-stack`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="10" y="6" width="44" height="14" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.18"/><rect x="10" y="24" width="44" height="14" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.12"/><rect x="10" y="42" width="44" height="14" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.06"/></svg>
```

### Adapter / Plug (two interlocking shapes)

`service: adapter-plug`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="6" y="20" width="24" height="24" rx="4" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><rect x="34" y="20" width="24" height="24" rx="4" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.1"/><path d="M30 28 L34 28 M30 36 L34 36" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><circle cx="18" cy="32" r="4" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.2"/><circle cx="46" cy="32" r="4" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity="0.2"/></svg>
```

### Event / Trigger (gear with lightning)

`service: event-trigger`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="22" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.06"/><path d="M28 16 L36 16 L33 30 L40 30 L30 50 L33 36 L26 36 Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round" fill="currentColor" fill-opacity="0.2"/></svg>
```

### EDI / Data Exchange (arrows through document)

`service: edi-data-exchange`

```svg
<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="14" y="8" width="36" height="48" rx="3" stroke="currentColor" stroke-width="2.5" fill="currentColor" fill-opacity="0.08"/><path d="M22 24 L42 24 M38 20 L42 24 L38 28" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M42 40 L22 40 M26 36 L22 40 L26 44" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><line x1="22" y1="16" x2="42" y2="16" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-opacity="0.4"/><line x1="22" y1="48" x2="42" y2="48" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-opacity="0.4"/></svg>
```

## When a required icon is absent from the catalog

`icons.py`'s generic lookup only reads `assets/generic-icons.json` — there is no mechanism for a spec to supply inline SVG for a single node. Leave `service` unset (or use a slug that isn't in the catalog) and the node renders as a labeled colored placeholder instead, which is correct default behavior, not a degraded fallback.

Adding a genuinely new icon to the catalog means editing `assets/generic-icons.json` and this file together (the JSON is the data `icons.py` reads; this file is the same content in agent-readable form). New icons should match the existing visual language:

- `viewBox="0 0 64 64"`, `fill="none"`
- Primary strokes: `stroke="currentColor" stroke-width="2.5"`
- Enclosed fills: `fill="currentColor" fill-opacity="0.08"` to `0.2`
- Simple geometric primitives only: `rect`, `circle`, `ellipse`, `path`, `line`, `polyline`
- Visual weight/density must match the catalog above
- Keep path data concise — no organic/complex curves
