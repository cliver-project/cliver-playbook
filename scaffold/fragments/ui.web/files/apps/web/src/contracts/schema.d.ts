// Generated from contracts/openapi.yaml by `pnpm contracts:generate`.
// Do not edit by hand; run `make contracts` after changing a fragment.

export interface paths {
    "/api/v1/agent/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start an agent run */
        post: operations["createAgentRun"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/runs/{run_id}/events": {
        parameters: {
            query?: never;
            header?: {
                /** @description Replay starts after this event sequence. The stream always ends with the run's terminal event; reconnecting clients resume instead of re-executing the run. */
                "Last-Event-ID"?: number;
            };
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        /** Stream run events as server-sent events */
        get: operations["streamAgentRun"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/runs/{run_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel a run */
        post: operations["cancelAgentRun"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/runs/{run_id}/feedback": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Rate an agent result and run the learning evaluation */
        post: operations["submitAgentFeedback"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List recent conversation sessions */
        get: operations["listAgentSessions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/sessions/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        /** Read a conversation session and its replayable run events */
        get: operations["getAgentSession"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/proposals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List improvement proposals (reviewer only) */
        get: operations["listAgentProposals"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/proposals/{proposal_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve a proposal and apply prompt guidance */
        post: operations["approveAgentProposal"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/proposals/{proposal_id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reject a proposal without changing runtime behaviour */
        post: operations["rejectAgentProposal"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/golden-cases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List offline regression cases (reviewer only) */
        get: operations["listAgentGoldenCases"];
        put?: never;
        /** Add an offline regression case */
        post: operations["createAgentGoldenCase"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/golden-cases/{case_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                case_id: number;
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete an offline regression case */
        delete: operations["deleteAgentGoldenCase"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/proposals/{proposal_id}/regression": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        /** Read the latest offline gate report for a proposal */
        get: operations["getAgentProposalRegression"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/golden-set/publish": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Publish the current golden cases as an immutable version */
        post: operations["publishAgentGoldenSet"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/golden-set/versions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List golden-set versions for one agent */
        get: operations["listAgentGoldenSetVersions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/golden-set/versions/{version_id}/activate": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                version_id: number;
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Activate, or roll back to, a golden-set version */
        post: operations["activateAgentGoldenSetVersion"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/agents/{name}/learning": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        /** Per-agent learning, proposal and version summary */
        get: operations["getAgentLearningSummary"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/agents/{name}/config/versions": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        /** List prompt-configuration versions */
        get: operations["listAgentConfigVersions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/agents/{name}/config/rollout": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Set the staged rollout percentage for the active prompt config */
        post: operations["setAgentConfigRollout"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/agents/{name}/config/rollback/{version}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
                version: number;
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Roll the active prompt configuration back to a version */
        post: operations["rollbackAgentConfig"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/runtime": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read safe runtime configuration status */
        get: operations["getAgentRuntimeStatus"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/agents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List the coordinator's registered sub-agents */
        get: operations["listAgentCatalog"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/agents/{name}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        /** Describe one registered sub-agent */
        get: operations["getAgentCatalogEntry"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/register": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Register a new account */
        post: operations["register"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Sign in with username and password */
        post: operations["login"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Return the current user */
        get: operations["me"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update the current user's profile */
        patch: operations["updateProfile"];
        trace?: never;
    };
    "/api/v1/products": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List products */
        get: operations["listProducts"];
        put?: never;
        /** Create a product */
        post: operations["createProduct"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/products/{product_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                product_id: number;
            };
            cookie?: never;
        };
        /** Get one product */
        get: operations["getProduct"];
        put?: never;
        post?: never;
        /** Delete a product */
        delete: operations["deleteProduct"];
        options?: never;
        head?: never;
        /** Update a product */
        patch: operations["updateProduct"];
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        AgentRunRequest: {
            message: string;
            session_id?: string;
            attachments?: string[];
        };
        AgentRunCreated: {
            run_id: string;
            /** @enum {string} */
            status: "queued" | "running" | "completed" | "failed" | "cancelled";
        };
        AgentFeedbackRequest: {
            agent: string;
            /** Format: int64 */
            rating: number;
            comment?: string;
            /**
             * Format: int32
             * @description Omit to rate the agent's latest step in the run.
             */
            step?: number | null;
        };
        AgentEvaluationSummary: {
            /** @enum {string} */
            status: "evaluated";
            agent: string;
            metric: string;
            score: number;
            passed: boolean;
            details: {
                [key: string]: unknown;
            };
        };
        AgentProposal: {
            id: string;
            agent: string;
            /** @enum {string} */
            kind: "prompt" | "tool" | "policy";
            /** @enum {string} */
            status: "pending" | "approved" | "applied" | "rejected";
            title: string;
            rationale: string;
            patch: {
                [key: string]: unknown;
            };
            evidence: {
                [key: string]: unknown;
            };
            /** Format: date-time */
            created_at: string;
            reviewed_by?: number | null;
            /** Format: date-time */
            reviewed_at?: string | null;
            /** Format: date-time */
            applied_at?: string | null;
        };
        AgentProposalList: {
            proposals: components["schemas"]["AgentProposal"][];
        };
        AgentFeedbackCreated: {
            /** Format: int64 */
            feedback_id: number;
            /** Format: int64 */
            experience_id: number;
            evaluation: components["schemas"]["AgentEvaluationSummary"];
            proposal?: components["schemas"]["AgentProposal"] | null;
        };
        AgentProposalDecision: {
            proposal: components["schemas"]["AgentProposal"];
            applied: boolean;
            requires_manual_apply: boolean;
            regression?: components["schemas"]["AgentRegression"] | null;
        };
        AgentProposalRejectRequest: {
            note?: string;
        };
        AgentGoldenCaseCreate: {
            agent: string;
            name: string;
            message: string;
            expected_contains?: string[];
            forbidden_contains?: string[];
        };
        AgentGoldenCase: {
            /** Format: int64 */
            id: number;
            agent: string;
            name: string;
            message: string;
            expected_contains: string[];
            forbidden_contains: string[];
            enabled: boolean;
            /** Format: date-time */
            created_at: string;
            /** Format: date-time */
            updated_at: string;
        };
        AgentGoldenCaseList: {
            cases: components["schemas"]["AgentGoldenCase"][];
        };
        AgentRegression: {
            /** Format: int64 */
            id: number;
            proposal_id: string;
            agent: string;
            /** @enum {string} */
            status: "passed" | "failed" | "error" | "skipped";
            baseline_score: number;
            candidate_score: number;
            min_score: number;
            case_results: Record<string, never>[];
            error: string;
            /** Format: date-time */
            created_at: string;
        };
        AgentGoldenSetPublishRequest: {
            agent: string;
            note?: string;
        };
        AgentGoldenSetVersion: {
            /** Format: int64 */
            id: number;
            agent: string;
            /** Format: int32 */
            version: number;
            cases: Record<string, never>[];
            note: string;
            created_by?: number | null;
            is_active: boolean;
            /** Format: date-time */
            created_at: string;
        };
        AgentGoldenSetVersionList: {
            versions: components["schemas"]["AgentGoldenSetVersion"][];
        };
        AgentConfigVersion: {
            /** Format: int64 */
            id: number;
            agent: string;
            /** Format: int32 */
            version: number;
            prompt_overlay: string;
            /** Format: int32 */
            rollout_percent: number;
            source_proposal_id?: string | null;
            note: string;
            created_by?: number | null;
            /** Format: date-time */
            created_at: string;
        };
        AgentConfigVersionList: {
            versions: components["schemas"]["AgentConfigVersion"][];
        };
        AgentConfigRollbackRequest: {
            note?: string;
        };
        AgentConfigRolloutRequest: {
            /** Format: int32 */
            percent: number;
            note?: string;
        };
        AgentLearningSummary: {
            agent: string;
            config_version?: number | null;
            /** Format: int64 */
            config_versions: number;
            prompt_overlay: string;
            /** Format: int32 */
            rollout_percent: number;
            active_golden_version?: number | null;
            /** Format: int64 */
            golden_versions: number;
            proposal_counts: {
                [key: string]: number;
            };
            /** Format: int64 */
            feedback_count: number;
            /** Format: int64 */
            positive_feedback: number;
            recent_pass_rate?: number | null;
            /** Format: int64 */
            recent_evaluations: number;
            /** Format: date-time */
            generated_at: string;
        };
        AgentDescriptor: {
            name: string;
            description: string;
            capabilities: string[];
            /** @enum {string} */
            autonomy_mode: "off" | "proposal" | "auto";
            has_pipeline: boolean;
        };
        AgentRuntimeStatus: {
            model_configured: boolean;
            judge_enabled: boolean;
            mcp_enabled: boolean;
            compaction_enabled: boolean;
            tool_permission_mode: string;
            system_one_provider: string;
            model_provider?: string;
            model_name?: string;
            mcp_servers?: string[];
        };
        AgentSessionRead: {
            session_id: string;
            last_message: string;
            run_count: number;
            /** Format: date-time */
            updated_at: string;
        };
        AgentSessionList: {
            sessions: components["schemas"]["AgentSessionRead"][];
        };
        AgentSessionRunRead: {
            run_id: string;
            message: string;
            status: string;
            /** Format: date-time */
            created_at: string;
            /** @description Stored run events in sequence order, capped per run. */
            events: {
                [key: string]: unknown;
            }[];
        };
        AgentSessionDetail: {
            session_id: string;
            runs: components["schemas"]["AgentSessionRunRead"][];
        };
        AgentList: {
            agents: components["schemas"]["AgentDescriptor"][];
        };
        RegisterRequest: {
            username: string;
            password: string;
            /** Format: email */
            email?: string | null;
            /** @default  */
            display_name: string;
        };
        LoginRequest: {
            username: string;
            password: string;
        };
        LoginResponse: {
            token: string;
            must_change_password: boolean;
            user: components["schemas"]["UserRead"];
        };
        MeResponse: {
            user: components["schemas"]["UserRead"];
        };
        ProfileUpdate: {
            /** Format: email */
            email?: string | null;
            phone?: string | null;
            display_name?: string;
        };
        UserRead: {
            /** Format: int64 */
            id: number;
            username: string;
            email?: string | null;
            phone?: string | null;
            display_name: string;
            is_active: boolean;
            must_change_password: boolean;
            /** Format: date-time */
            created_at: string;
            role_codes?: string[];
            permissions?: string[];
        };
        Product: {
            /** Format: int64 */
            id: number;
            name: string;
            description: string;
            /** Format: int32 */
            price_cents: number;
            /** Format: date-time */
            created_at: string;
            /** Format: date-time */
            updated_at: string;
        };
        ProductCreate: {
            name: string;
            /** @default  */
            description: string;
            /**
             * Format: int32
             * @default 0
             */
            price_cents: number;
        };
        ProductUpdate: {
            name?: string;
            description?: string;
            /** Format: int32 */
            price_cents?: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    createAgentRun: {
        parameters: {
            query?: never;
            header?: {
                /** @description Optional client-generated key. Repeating the same key for the same user returns the existing run instead of creating another one. */
                "Idempotency-Key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentRunRequest"];
            };
        };
        responses: {
            /** @description Run accepted */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentRunCreated"];
                };
            };
        };
    };
    streamAgentRun: {
        parameters: {
            query?: never;
            header?: {
                /** @description Replay starts after this event sequence. The stream always ends with the run's terminal event; reconnecting clients resume instead of re-executing the run. */
                "Last-Event-ID"?: number;
            };
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description SSE stream; event types are defined in contracts/events.json */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/event-stream": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Invalid run id or Last-Event-ID header */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    cancelAgentRun: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Cancellation accepted */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    submitAgentFeedback: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentFeedbackRequest"];
            };
        };
        responses: {
            /** @description Feedback recorded; evaluation and proposal outcome */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentFeedbackCreated"];
                };
            };
            /** @description The run belongs to another user */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Run, agent or observed experience not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid rating, agent or step */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    listAgentSessions: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Sessions owned by the current user, newest first */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentSessionList"];
                };
            };
        };
    };
    getAgentSession: {
        parameters: {
            query?: {
                /** @description Maximum runs to return, newest selected first and replayed oldest-first. */
                limit?: number;
            };
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Session runs with stored events */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentSessionDetail"];
                };
            };
            /** @description No runs for this session belong to the current user */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    listAgentProposals: {
        parameters: {
            query?: {
                agent?: string;
                status?: "pending" | "approved" | "applied" | "rejected";
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Improvement proposals */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentProposalList"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    approveAgentProposal: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Proposal approved; prompt proposals also applied */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentProposalDecision"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Proposal not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Proposal was already reviewed */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Prompt proposal is empty, too large or the overlay is full */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    rejectAgentProposal: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["AgentProposalRejectRequest"];
            };
        };
        responses: {
            /** @description Proposal rejected */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentProposalDecision"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Proposal not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Proposal was already reviewed */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reject note is too long */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    listAgentGoldenCases: {
        parameters: {
            query?: {
                agent?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Golden cases */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentGoldenCaseList"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    createAgentGoldenCase: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentGoldenCaseCreate"];
            };
        };
        responses: {
            /** @description Golden case created */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentGoldenCase"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Agent not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description A case with this agent and name already exists */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Missing fields or no assertions */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    deleteAgentGoldenCase: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                case_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Case deleted */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Case not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    getAgentProposalRegression: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Regression report */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentRegression"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Proposal or report not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    publishAgentGoldenSet: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentGoldenSetPublishRequest"];
            };
        };
        responses: {
            /** @description Published golden-set version */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentGoldenSetVersion"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Agent not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description No enabled cases to publish */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    listAgentGoldenSetVersions: {
        parameters: {
            query: {
                agent: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Golden-set versions, newest first */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentGoldenSetVersionList"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    activateAgentGoldenSetVersion: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                version_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Active golden-set version */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentGoldenSetVersion"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Version not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    getAgentLearningSummary: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Agent learning summary */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentLearningSummary"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Agent not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    listAgentConfigVersions: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Config versions, newest first */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentConfigVersionList"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Agent not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    setAgentConfigRollout: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentConfigRolloutRequest"];
            };
        };
        responses: {
            /** @description Learning summary after the rollout change */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentLearningSummary"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Agent not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Rollout percent outside 0..100 */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    rollbackAgentConfig: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
                version: number;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["AgentConfigRollbackRequest"];
            };
        };
        responses: {
            /** @description Learning summary after rollback */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentLearningSummary"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Agent or config version not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    getAgentRuntimeStatus: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Runtime feature flags without secrets */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentRuntimeStatus"];
                };
            };
            /** @description Reviewer permission required */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    listAgentCatalog: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Registered sub-agents */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentList"];
                };
            };
        };
    };
    getAgentCatalogEntry: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Sub-agent descriptor */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentDescriptor"];
                };
            };
            /** @description Agent not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    register: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegisterRequest"];
            };
        };
        responses: {
            /** @description Account created and signed in */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginResponse"];
                };
            };
            /** @description Username or email already in use */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    login: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Signed in */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginResponse"];
                };
            };
            /** @description Invalid credentials */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    me: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Current user */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MeResponse"];
                };
            };
            /** @description Invalid or expired token */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    updateProfile: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProfileUpdate"];
            };
        };
        responses: {
            /** @description Updated user */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MeResponse"];
                };
            };
        };
    };
    listProducts: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Products ordered by newest first */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Product"][];
                };
            };
        };
    };
    createProduct: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductCreate"];
            };
        };
        responses: {
            /** @description Created product */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Product"];
                };
            };
        };
    };
    getProduct: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                product_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Product */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Product"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    deleteProduct: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                product_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Deleted */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    updateProduct: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                product_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductUpdate"];
            };
        };
        responses: {
            /** @description Updated product */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Product"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
}
