# Fault Domain Patterns

Reference for identifying fault domains and SRE production concerns by
component type. Use during Step 3 of the observe workflow.

---

## Fault Domains by Component Type

### HTTP / API Server

| Fault Domain | Failure Mode | Observable Signal |
|--------------|--------------|-------------------|
| Connectivity | Port not reachable, TLS handshake failure | Connection error counter, health check failure |
| Latency | Slow handler, upstream dependency delay | Request duration histogram (p95/p99), span waterfall |
| Errors | 4xx/5xx responses, panic/crash | Error rate counter by status code, error log with stack |
| Capacity | Max connections reached, thread/goroutine exhaustion | Active connections gauge, goroutine/thread count |
| Availability | Process crash, OOM kill, deployment gap | Health endpoint status, uptime gauge |

### Database (SQL / NoSQL)

| Fault Domain | Failure Mode | Observable Signal |
|--------------|--------------|-------------------|
| Connectivity | Connection refused, auth failure, DNS | Connection error counter, connection pool stats |
| Latency | Slow queries, lock contention, index miss | Query duration histogram, slow query log events |
| Data Integrity | Deserialization error, schema mismatch, constraint violation | Deserialization error counter, validation failure log |
| Capacity | Connection pool exhaustion, disk full, memory limit | Pool active/idle gauge, storage utilization gauge |
| Availability | Primary down, failover in progress, replication lag | Replication lag gauge, failover event log |

### Cache (Redis, Memcached)

| Fault Domain | Failure Mode | Observable Signal |
|--------------|--------------|-------------------|
| Connectivity | Connection lost, cluster redirect failure | Connection error counter, reconnect event log |
| Latency | Large key scan, memory pressure, network hop | Operation duration histogram |
| Data Integrity | Eviction of needed keys, TTL expiry race | Cache miss rate counter, eviction counter |
| Capacity | Max memory reached, connection limit | Memory usage gauge, eviction rate |
| Availability | Single node failure, cluster partition | Health check failure, cluster state log |

### Message Queue / Broker (Kafka, RabbitMQ, Redis queues, NATS)

| Fault Domain | Failure Mode | Observable Signal |
|--------------|--------------|-------------------|
| Connectivity | Broker unreachable, auth failure | Connection error counter |
| Latency | Consumer lag, slow processing | Consumer lag gauge, processing duration histogram |
| Data Integrity | Serialization error, poison pill message, duplicate delivery | Deserialization error counter, dead letter queue depth |
| Capacity | Queue depth growing unbounded, partition limit | Queue depth gauge, partition count |
| Availability | Broker down, leader election in progress | Broker health gauge, rebalance event log |
| Ordering | Out-of-order delivery, rebalance causing reprocessing | Sequence gap counter, rebalance event log |

### External HTTP / gRPC APIs

| Fault Domain | Failure Mode | Observable Signal |
|--------------|--------------|-------------------|
| Connectivity | DNS failure, connection refused, TLS error | Outbound connection error counter |
| Latency | Slow upstream, timeout | Outbound request duration histogram |
| Errors | 4xx/5xx from upstream, malformed response | Outbound error rate by status, error log |
| Availability | Upstream outage, rate limiting (429) | Circuit breaker state gauge, retry counter |
| Contract | Schema change, unexpected response format | Deserialization error counter, validation failure log |

### File Storage (S3, GCS, Local FS)

| Fault Domain | Failure Mode | Observable Signal |
|--------------|--------------|-------------------|
| Connectivity | Bucket/path not accessible, permission denied | Access error counter |
| Latency | Large file transfer, throttled requests | Operation duration histogram, transfer size histogram |
| Data Integrity | Corrupt file, incomplete upload/download | Checksum mismatch counter, integrity error log |
| Capacity | Disk full, quota exceeded, rate limit | Storage usage gauge, throttle event counter |

### Background Workers / Scheduled Jobs

| Fault Domain | Failure Mode | Observable Signal |
|--------------|--------------|-------------------|
| Execution | Job failed, panic, timeout | Job error counter, execution duration histogram |
| Scheduling | Missed schedule, overlapping execution | Missed tick counter, concurrent execution gauge |
| Data | Processing stale data, input validation error | Staleness gauge, validation error counter |
| Capacity | Worker pool exhaustion, memory growth | Active workers gauge, memory usage gauge |

---

## Cross-Cutting SRE Concerns

These failure patterns span multiple components and are common in
production systems.

### Cascading Failure

**Pattern**: Component A fails, causes Component B to queue up, which
exhausts Component C's resources.

**Observable signals**:
- Error rate spike in upstream + latency spike in downstream
- Connection pool depletion spreading across services
- Queue depth growing in multiple queues simultaneously

**Mitigations to look for**: Circuit breakers, bulkheads, timeouts,
graceful degradation.

### Retry Storm

**Pattern**: Failures cause clients to retry aggressively, amplifying load.

**Observable signals**:
- Request rate multiplier (actual vs expected traffic)
- Retry counter per client
- Server error rate rising with retry rate

**Mitigations**: Exponential backoff, jitter, retry budgets.

### Thundering Herd

**Pattern**: Many clients wake up simultaneously (cache expiry, leader
election, config reload).

**Observable signals**:
- Traffic spike at specific intervals
- Cache miss rate spike
- Sudden connection pool saturation

**Mitigations**: Cache stampede locks, staggered TTLs, jitter on timers.

### Poison Pill

**Pattern**: A malformed message or request causes repeated processing
failures, blocking the queue.

**Observable signals**:
- Single message with high retry count
- Dead letter queue growing
- Consumer error rate from specific message ID

**Mitigations**: Dead letter queues, max retry limits, message validation.

### Head-of-Line Blocking

**Pattern**: A slow request or message blocks processing of faster ones
behind it.

**Observable signals**:
- P99 latency much higher than P50
- Queue wait time growing while processing time is stable
- Individual slow spans in trace waterfall

**Mitigations**: Separate queues by priority, async processing, timeouts.

### Stale State / Split Brain

**Pattern**: Caches or replicas serve outdated data, or cluster nodes
disagree on state.

**Observable signals**:
- Cache hit serving stale data (version mismatch)
- Replication lag gauge
- Inconsistent read results across replicas

**Mitigations**: TTLs, version vectors, consistency checks.

### Cold Start

**Pattern**: Fresh instances have empty caches and cold connection pools,
causing elevated latency.

**Observable signals**:
- High latency in first N minutes after deployment
- Cache miss rate spike post-deploy
- Connection pool warm-up time

**Mitigations**: Warm-up scripts, gradual traffic shift, pre-population.

---

## Mapping Fault Domains to Alert Severity

| Fault Domain | Typical Severity | Rationale |
|--------------|------------------|-----------|
| Connectivity loss to primary DB | Critical | Complete service impact |
| Connectivity loss to cache | Warning | Degraded performance, fallback to DB |
| Latency p99 > 5x baseline | Warning | User-impacting but functional |
| Error rate > 50% | Critical | Majority of requests failing |
| Error rate > 5% | Warning | Noticeable degradation |
| Queue depth growing > 10min | Warning | Processing falling behind |
| Pool utilization > 90% | Warning | Approaching saturation |
| Memory usage > 80% | Warning | OOM risk approaching |
| Scheduled job missed | Warning | Data staleness risk |
| Deserialization errors | Warning | Data integrity concern |
