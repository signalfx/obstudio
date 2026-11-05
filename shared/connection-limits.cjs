// Backend bounds: credentials/bounded.go permits 5 s per native operation.
// A reference uses at most Get + Set + read-back. connection_secrets.go cleans
// at most two references per pass; an unconfirmed reference uses Get + Delete.
const nativeCredentialOperationTimeoutMs = 5_000;
const nativeReferenceOperations = 3;
const maxCredentialCleanupReferences = 2;
const nativeCredentialBudgetMs = (nativeReferenceOperations + 2 * maxCredentialCleanupReferences) * nativeCredentialOperationTimeoutMs;
const replyGraceMs = 5_000;

// api/splunk_export.go bounds its connection probe to 10 s.
const cloudMutationTimeoutMs = 10_000 + nativeCredentialBudgetMs + replyGraceMs;
// Connection actions may read status before a mutation and reconcile after a lost reply.
const cloudHostRequestTimeoutMs = 15_000 + cloudMutationTimeoutMs + 15_000 + replyGraceMs;

// Initialization can refresh the managed connection, import an IDE credential,
// then fall back to a status read after a failure. Bound both connection phases.
const cloudInitializeHostRequestTimeoutMs = 2 * cloudHostRequestTimeoutMs + replyGraceMs;

module.exports = { cloudMutationTimeoutMs, cloudHostRequestTimeoutMs, cloudInitializeHostRequestTimeoutMs };
