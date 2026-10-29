/*
 * Copyright (c) 2026 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// Generated from Rust IPC types. Do not edit.
export type SafeError = "unauthorized_window" | "invalid_endpoint" | "insecure_transport" | "invalid_certificate" | "credential_unavailable" | "credential_missing" | "invalid_credential" | "timeout" | "tls" | "network" | "redirect" | "unauthorized" | "forbidden" | "server" | "invalid_response" | "response_too_large" | "busy" | "invalid_input" | "not_found" | "cursor_expired" | "conflict" | "authentication_unavailable" | "runtime_not_ready" | "stale_context" | "compatibility_unverified" | "storage" | "profile_corrupt" | "duplicate_name" | "not_connected" | "scope_required";
export type FoundationInfo = { version: string, phase: string, credentialBackend: string, serverConnected: boolean, };
export type StorageChoice = "persistent" | "session_only";
export type CredentialWriteRequest = { secret: string, storage: StorageChoice, };
export type CredentialWriteReceipt = { storage: StorageChoice, };
export type DiagnosticKind = "service" | "integrations";
export type DiagnosticItem = { field: string, status: string, };
export type HostDiagnostic = { host: string, status: string, checks: Array<DiagnosticItem>, };
export type DiagnosticReport = { checkedAt: number, exitCode: number, cliVersion?: string, items: Array<DiagnosticItem>, hosts: Array<HostDiagnostic>, };
export type Authentication = "unauthenticated_loopback" | "bearer";
export type ProfileView = { id: string, revision: number, name: string, endpoint: string, authentication: Authentication, caPem: string | null, compatibility: string | null, credentialState: CredentialState, };
export type ProfileInput = { id: string | null, revision: number | null, name: string, endpoint: string, authentication: Authentication, caPem: string | null, compatibility: string | null, keepCredential: boolean, credential: CredentialWriteRequest | null, };
export type CredentialState = "not_required" | "stored" | "session_only" | "missing";
export type Fact<T> = { value: T | null, error: ApiFailure | null, };
export type DiscoveryStatus = "supported" | "missing" | "denied" | "unavailable" | "invalid" | "incompatible";
export type CompatibilityReason = "product_mismatch" | "schema_version" | "api_version" | "discovery_missing" | "discovery_denied" | "discovery_unavailable" | "invalid_discovery" | "qualification_required" | "qualified_profile" | "feature_missing" | "feature_version" | "operation_missing";
export type CompatibilityStatus = "qualified" | "unsupported" | "unverified";
export type OperationCompatibility = { status: CompatibilityStatus, reason: CompatibilityReason, qualificationId: string | null, };
export type DiscoveryResult = { status: DiscoveryStatus, server: ServerInfo | null, error: ApiFailure | null, reason: CompatibilityReason | null, operations: { [key in string]: OperationCompatibility }, };
export type CheckReport = { connectionId: string, revision: number, checkedAt: number, liveness: Fact<HealthResponse>, readiness: Fact<ReadinessResponse>, identity: Fact<AccessMeResponse>, capabilities: Fact<Capabilities>, compatibilityVerified: boolean, anonymousAccess: boolean, supportedOperations: Array<string>, discovery?: DiscoveryResult, };
export type CompatibilityProfile = { id: string, serverCommit: string, contractSha256: string, artifactSha256: string, operations: Array<string>, evidence: string, };
export type ActiveView = { connectionId: string, generation: number, report: CheckReport, scope: ScopeDescriptor | null, };
export type MemoryContext = { connectionId: string, endpoint: string, principal: AccessPrincipal | null, generation: number, scopeId: string, };
export type WriteStatus = "pending" | "succeeded" | "failed" | "unknown";
export type WriteRecord = { operationId: string, context: MemoryContext, status: WriteStatus, references: Array<ArtifactReference>, error: ApiFailure | null, };
export type WriteOutcome = { record: WriteRecord, result: MemorySaveResponse | null, };
export type DesktopState = { generation: number, profiles: Array<ProfileView>, reports: Array<CheckReport>, active: ActiveView | null, compatibilityProfiles: Array<CompatibilityProfile>, pendingCredentialCleanup: number, lastWrite: WriteRecord | null, };
export type ApiFailure = { code: SafeError, requestId: string | null,
/**
 * Conservatively true once handed to the HTTP client, even if delivery is uncertain.
 */
dispatched: boolean, };
export type MemorySaveResponse = { changed: boolean, records: Array<AtomicMemoryRecord>, };
export type MemorySearchHit = { artifact: ArtifactReference, text: string, score: number, matched_by: Array<string>, };
export type MemorySearchResponse = { hits: Array<MemorySearchHit>, };
export type AtomicMemoryDetail = { artifact: ArtifactReference, kind: string, text: string, source_refs: Array<SourceTypeReference>, };
export type ObservationUnit = "http_request" | "user_operation";
export type ObservedOperation = "get_liveness" | "get_server_info" | "get_readiness" | "get_capabilities" | "get_access_principal" | "list_scopes" | "get_scope" | "get_default_scope" | "remember_memory" | "search_memory" | "get_artifact_revision";
export type ObservationOutcome = "success" | "failure" | "cancelled" | "unknown";
export type SessionObservation = { unit: ObservationUnit, operation: ObservedOperation, outcome: ObservationOutcome, completedAtMs: number, durationMs: number, httpStatus: number | null, errorCode: SafeError | null, };
export type OutcomeCounts = { success: number, failure: number, cancelled: number, unknown: number, };
export type OperationSummary = { unit: ObservationUnit, operation: ObservedOperation, outcomes: OutcomeCounts, sampleCount: number, minDurationMs: number, meanDurationMs: number, maxDurationMs: number, };
export type SessionCoverage = { desktopSessionOnly: boolean, persistenceEvidence: boolean, httpOperations: Array<ObservedOperation>, userOperations: Array<ObservedOperation>, identityChecksIncluded: boolean, installerOps: boolean, };
export type SessionSummary = { schemaVersion: number, sessionStartedAtMs: number, windowStartedAtMs: number, generatedAtMs: number, capacity: number, evicted: number,
/**
 * Process-lifetime loss count, deliberately not cleared by a window reset.
 */
droppedSinceStart: number, coverage: SessionCoverage, operations: Array<OperationSummary>, recent: Array<SessionObservation>, };
export type AccessAction = "server.observe" | "server.admin" | "scope.read" | "scope.contribute" | "scope.review" | "scope.delegate" | "scope.admin" | "artifact.read" | "artifact.write" | "artifact.share" | "handoff.evidence.inspect" | "handoff.acknowledge" | "prompt.use";
export type AccessControlMode = "disabled" | "enforced";
export type AccessMeResponse = { principal: AccessPrincipal, mode: AccessControlMode, resource_kinds: Array<AccessResourceType>, provider_capabilities: AccessProviderCapabilities, artifact_families: Array<ArtifactFamilyAccessCapability>, };
export type AccessPrincipal = { type: Type, id: string, description?: string | null, };
export type AccessProviderCapabilities = { safe_resource_filtering: boolean, multi_requirement_check: boolean, relationship_management: boolean, group_subjects: boolean, multi_principal: boolean, max_direct_resource_keys: number, };
export type AccessResourceType = "server" | "scope" | "artifact";
export type AccessRole = "handoff.viewer" | "handoff.receiver" | "artifact.viewer" | "prompt.user" | "artifact.owner" | "scope.viewer" | "scope.contributor" | "scope.reviewer" | "scope.delegator" | "scope.admin" | "server.observer" | "server.admin";
export type ArtifactDreamingOperationCapability = { operation: DreamOperation, output_kind: OutputKind, effect: Effect, };
export type ArtifactFamilyAccessCapability = { family: string, enabled: boolean, share_unit: ShareUnit, actions: Array<AccessAction>, grantable_roles: Array<AccessRole>, };
export type ArtifactReadFamily = "memory" | "atomic-memory" | "experience" | "skill" | "handoff" | "profile" | "prompt" | "topic-memory";
export type ArtifactReference = { family: string, artifact_id: string, revision: number, };
export type ArtifactRevision = { scope_id: string, family: ArtifactReadFamily, artifact_id: string, revision: number, content: Record<string, unknown>, sources: Array<SourceTypeReference>, artifacts: Array<ArtifactReference>, content_digest: string,
/**
 * When this revision was committed. Absent for revisions stored before this field existed.
 */
created_at?: string | null,
/**
 * Principal that committed a rollback. Ordinary revisions omit it.
 */
created_by?: AccessPrincipal | null,
/**
 * Historical revision restored by this rollback.
 */
restored_from_revision?: number | null,
/**
 * Reason recorded for a rollback.
 */
reason?: string | null, };
export type AtomicMemoryRecord = { artifact: ArtifactReference, kind: string, text: string, state: AtomicMemoryState, state_version: number, merged_into_id: string | null, };
export type AtomicMemorySearchHit = { memory: AtomicMemoryRecord,
/**
 * Raw RRF score. Hybrid mode applies the deployment's normalized relative FTS/vector weights.
 */
score: number, matched_by: Array<MatchedBy>, };
export type AtomicMemorySearchMode = "text" | "vector" | "hybrid";
export type AtomicMemoryState = "active" | "forgotten" | "merged" | "retired";
export type BuiltinProfile = "coding" | "conversation";
export type Capabilities = { prompts?: { [key in string]: PromptCapability },
/**
 * Whether asynchronous Artifact Dream execution is configured.
 */
artifact_dreaming?: boolean,
/**
 * Dream operations enabled by the current Runtime, including their reviewed effect.
 */
artifact_dreaming_operations?: Array<ArtifactDreamingOperationCapability>, source_types: Array<string>, artifact_families: Array<string>,
/**
 * Whether pending Sources can be extracted into Memory.
 */
memory_extraction: boolean, extraction?: ExtractionStatus,
/**
 * Whether the configured model can generate reviewed Experience Candidates.
 */
experience_generation?: boolean,
/**
 * Whether the configured model can generate reviewed managed Skill Candidates.
 */
managed_skill_generation?: boolean,
/**
 * Whether host-local external Skill discovery and exact resolution are configured.
 */
external_skill_registry?: boolean,
/**
 * Whether exact evidence can be generated into an inspectable Handoff Draft.
 */
handoff_generation: boolean, search_modes: Array<MemorySearchMode>, context_versions: Array<PreparedContextSchema>, };
export type Configuration = "configured" | "unconfigured" | "unknown";
export type ContractVersion = { major: number, minor: number, };
export type DreamOperation = "refine_experience" | "derive_skill" | "revise_skill" | "revise_profile" | "revise_memory" | "revise_topic_memory" | "refresh_handoff" | "revise_prompt" | "revise_tags";
export type Effect = "review_then_publish" | "review_then_publish_configuration" | "review_then_replace_tags";
export type ExtractionBackground = {
/**
 * Placement of the Memory Supervisor. None means no background executor; synchronous flush may still work.
 */
location: Location,
/**
 * Current local Supervisor leadership role. Standby is normal; null means no running local Supervisor.
 */
role?: Role | null,
/**
 * Local Supervisor lifecycle and control state, independent of individual worker outcomes. A running Supervisor may be retrying failed workers. External state is unknown.
 */
state: State,
/**
 * Whether this process schedules automatic Memory extraction. False still permits explicit flush and recovery of accepted work. Null means the external worker schedule is unknown.
 */
automatic_processing_enabled?: boolean | null, };
export type ExtractionFailure = {
/**
 * Sanitized category: model_configuration_error, model_timeout, model_unavailable, invalid_model_output, worker_timeout, worker_crash, invalid_worker_result, missing_durable_acknowledgement, supervisor_failed, lease_renewal_failed, scope_discovery_failed, or processing_failed. Raw exception messages, model inputs, and credentials are never returned.
 */
code: string,
/**
 * Inference for recognized model failures; otherwise the boundary where failure was observed. Flush or worker does not identify the failing internal component.
 */
stage: Stage,
/**
 * UTC time when this process observed the failure.
 */
occurred_at: string, };
export type ExtractionObservation = {
/**
 * Unverified means no execution outcome or control failure has been observed in this window. Observed means at least one success or failure is recorded; neither value is a health verdict.
 */
status: ExtractionObservationStatus,
/**
 * UTC start of this Runtime's observation window. Records cover this process and its child Memory workers, reset on Runtime restart, and do not include remote workers or a durable per-Scope failure history.
 */
since: string, last_failure?: ExtractionFailure,
/**
 * UTC time of the most recent local successful nonempty synchronous flush or acknowledged Memory worker invocation. This does not prove that a model was called or that any previous failure has recovered.
 */
last_success_at?: string | null, };
export type ExtractionObservationStatus = "unverified" | "observed";
export type ExtractionStatus = {
/**
 * Whether a local extraction model or custom pipeline is assembled. Configured does not verify credentials or connectivity. Unknown means execution is external and its configuration is not observed.
 */
configuration: Configuration, background: ExtractionBackground, observation: ExtractionObservation, };
export type FeatureContract = { version: ContractVersion, operations: Array<string>, };
export type HealthResponse = { status: string, };
export type Location = "local" | "external" | "none";
export type MatchedBy = "text" | "vector";
export type MemoryMutationResponse = { changed: boolean, records: Array<AtomicMemoryRecord>, };
export type MemorySearchMode = "auto" | "fts" | "vector" | "hybrid";
export type OutputKind = "candidate" | "tag_candidate";
export type PreparedContextSchema = "powercontext.prepared-context.v1";
export type Product = "powercontext";
export type PromptCapability = { status: PromptCapabilityStatus, reason: Reason | null, definition_version: string, builtin_version: string, builtin_profile: BuiltinProfile | null, };
export type PromptCapabilityStatus = "supported" | "disabled" | "unsupported";
export type ReadinessResponse = { status: ReadinessStatus, checks: { [key in string]: string }, };
export type ReadinessStatus = "ready" | "degraded" | "not_ready";
export type Reason = "operation_disabled" | "provider_not_configured" | "injected_component";
export type RememberMemoryRequest = { scope_id: string, kind: string,
/**
 * Must not exceed 8192 UTF-8 bytes after normalization.
 */
text: string, reason?: string | null, expected_revision?: number | null, };
export type Role = "leader" | "standby";
export type ScopeDescriptor = { scope_id: string, title: string, summary: string, parent_scope_id?: string | null, context_references: Array<string>, external_references: Array<ScopeExternalReference>, version: number, };
export type ScopeExternalReference = { kind: string, value: string, };
export type ScopePage = { items: Array<ScopeDescriptor>, next_cursor?: string | null, };
export type ScopeQueryField = "scope_id" | "title" | "summary" | "external_reference_value" | "binding_external_id";
export type SearchMemoryRequest = { tag_filter?: TagFilter, scope_id: string, query: string, limit?: number, mode?: MemorySearchMode, };
export type SearchMemoryResponse = { mode: AtomicMemorySearchMode, hits: Array<AtomicMemorySearchHit>, };
export type ServerInfo = {
/**
 * Compatibility version for this response shape and field semantics.
 */
schema_version: ContractVersion, product: Product,
/**
 * Opaque identity of the durable Server deployment. It is unrelated to Access deployment_id and remains stable across restarts, upgrades, backup restore and replicas sharing the same primary database.
 */
server_id: string, package_version: string,
/**
 * Major/minor projection of the OpenAPI info.version served by this package.
 */
api_contract_version: ContractVersion,
/**
 * Stable feature groups keyed by contract name.
 */
feature_contracts: { [key in string]: FeatureContract }, };
export type ShareUnit = "artifact" | "memory_entry";
export type SourceTypeReference = {
/**
 * Stable Source type, including dynamically registered Source names.
 */
source_type: string,
/**
 * Source identity as accepted at ingestion, including Unicode and interior spaces.
 */
source_id: string, };
export type Stage = "inference" | "flush" | "worker" | "supervisor" | "lease_renewal" | "scope_discovery";
export type State = "running" | "degraded" | "stopped" | "unknown";
export type TagFilter = { tags: Array<string>, match?: TagMatch, };
export type TagMatch = "all" | "any";
export type Type = "user" | "service";
