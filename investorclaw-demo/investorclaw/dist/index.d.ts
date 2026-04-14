/**
 * InvestorClaw — OpenClaw native plugin entry point.
 *
 * Wraps the Python-based investorclaw.py CLI as a set of typed agent tools.
 * Each tool spawns `python3 investorclaw.py <command>` in a subprocess with
 * API-key env vars forwarded from the plugin config.
 */
declare const _default: {
    id: string;
    name: string;
    description: string;
    configSchema: import("openclaw/plugin-sdk/plugin-entry").OpenClawPluginConfigSchema;
    register: NonNullable<import("openclaw/plugin-sdk/plugin-entry").OpenClawPluginDefinition["register"]>;
} & Pick<import("openclaw/plugin-sdk/plugin-entry").OpenClawPluginDefinition, "kind" | "reload" | "nodeHostCommands" | "securityAuditCollectors">;
export default _default;
//# sourceMappingURL=index.d.ts.map