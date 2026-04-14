/**
 * InvestorClaw — OpenClaw native plugin entry point.
 *
 * Wraps the Python-based investorclaw.py CLI as a set of typed agent tools.
 * Each tool spawns `python3 investorclaw.py <command>` in a subprocess with
 * API-key env vars forwarded from the plugin config.
 */
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { Type } from "@sinclair/typebox";
import { execFile } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { promisify } from "node:util";
import * as path from "node:path";
const execFileAsync = promisify(execFile);
// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const ENV_KEYS = [
    "FINNHUB_KEY",
    "NEWSAPI_KEY",
    "MASSIVE_API_KEY",
    "ALPHA_VANTAGE_KEY",
    "FRED_API_KEY",
    "INVESTOR_CLAW_REPORTS_DIR",
    "INVESTOR_CLAW_PORTFOLIO_DIR",
    "INVESTORCLAW_CONSULTATION_ENABLED",
    "INVESTORCLAW_CONSULTATION_ENDPOINT",
    "INVESTORCLAW_CONSULTATION_MODEL",
    "INVESTORCLAW_CONSULTATION_HMAC_KEY",
];
// Generous timeout for analysis commands that hit external APIs (ms).
const ANALYSIS_TIMEOUT_MS = 120_000;
// Faster timeout for read-only / local commands.
const QUICK_TIMEOUT_MS = 30_000;
// ---------------------------------------------------------------------------
// Plugin entry
// ---------------------------------------------------------------------------
export default definePluginEntry({
    id: "investorclaw",
    name: "InvestorClaw",
    description: "Portfolio analysis: holdings snapshots, performance metrics, bond analytics " +
        "(YTM, duration, FRED yield curve), analyst ratings, news correlation, and " +
        "CSV/Excel exports. Educational guardrails enforced on all outputs.",
    register(api) {
        const pluginConfig = (api.pluginConfig ?? {});
        // Resolve the skill directory: prefer INVESTORCLAW_SKILL_ROOT env/config,
        // then derive from this file's own location (works whether installed as a
        // linked plugin from the canonical repo or copied into extensions/).
        const selfDir = pluginConfig["INVESTORCLAW_SKILL_ROOT"] ??
            process.env.INVESTORCLAW_SKILL_ROOT ??
            path.dirname(new URL(import.meta.url).pathname);
        const entryScript = path.join(selfDir, "investorclaw.py");
        // ------------------------------------------------------------------
        // Helpers
        // ------------------------------------------------------------------
        /** Build a process env with plugin config keys forwarded. */
        function buildEnv() {
            const env = { ...process.env };
            for (const key of ENV_KEYS) {
                const val = pluginConfig[key];
                if (val)
                    env[key] = val;
            }
            // CRITICAL: Set PYTHONPATH so that 'from lib.xxx import ...' resolves correctly.
            // selfDir is the skill root (investorclaw/); lib/ is directly inside it.
            // Also include parent dir for any top-level package imports.
            const investorClawDir = path.dirname(selfDir); // parent of skill root
            const skillDir = selfDir; // skill root (investorclaw/)
            const pythonpath = `${investorClawDir}:${skillDir}`;
            if (env.PYTHONPATH) {
                env.PYTHONPATH = `${pythonpath}:${env.PYTHONPATH}`;
            }
            else {
                env.PYTHONPATH = pythonpath;
            }
            return env;
        }
        /**
         * Spawn `python3 investorclaw.py <command> [...args]` and return stdout.
         * On non-zero exit the stderr is captured and returned as content so the
         * agent can surface the error message rather than throwing.
         */
        async function run(command, args = [], timeoutMs = ANALYSIS_TIMEOUT_MS) {
            try {
                const env = buildEnv();
                console.log(`[InvestorClaw] Running: python3 ${entryScript} ${command}`);
                console.log(`[InvestorClaw] selfDir: ${selfDir}`);
                console.log(`[InvestorClaw] entryScript: ${entryScript}`);
                console.log(`[InvestorClaw] PYTHONPATH: ${env.PYTHONPATH}`);
                console.log(`[InvestorClaw] cwd: ${selfDir}`);
                const { stdout, stderr } = await execFileAsync("python3", [entryScript, command, ...args], { env, cwd: selfDir, timeout: timeoutMs });
                return (stdout || stderr).trim();
            }
            catch (err) {
                const e = err;
                return (e.stdout || e.stderr || e.message || String(err)).trim();
            }
        }
        // ------------------------------------------------------------------
        // Helpers
        // ------------------------------------------------------------------
        /** Wrap a text string as an AgentToolResult (content + required details). */
        function tr(text) {
            return { content: [{ type: "text", text }], details: {} };
        }
        /**
         * Run the analyst command and append any available SVG consultation cards
         * as ImageContent so the web UI can render them inline.
         */
        async function analystWithCards() {
            const text = await run("analyst");
            const content = [{ type: "text", text }];
            try {
                const env = buildEnv();
                const reportsBase = env.INVESTOR_CLAW_REPORTS_DIR
                    || path.join(process.env.HOME || "", "portfolio_reports");
                const cardsDir = path.join(reportsBase, ".raw", "consultation_cards");
                if (existsSync(cardsDir)) {
                    const files = readdirSync(cardsDir)
                        .filter(f => f.endsWith(".svg"))
                        .sort()
                        .slice(0, 20);
                    for (const file of files) {
                        const svg = readFileSync(path.join(cardsDir, file), "utf8");
                        content.push({
                            type: "image",
                            data: Buffer.from(svg).toString("base64"),
                            mimeType: "image/svg+xml",
                        });
                    }
                }
            }
            catch { /* non-fatal — text result still returned */ }
            return { content, details: {} };
        }
        // ------------------------------------------------------------------
        // Tools
        // ------------------------------------------------------------------
        api.registerTool({
            name: "investorclaw_setup",
            label: "Setup Portfolio",
            description: "Run initial portfolio setup. Discovers PDF, Excel, and CSV files in the " +
                "portfolios/ directory, extracts tables, and consolidates them into " +
                "master_portfolio.csv. Run this once before other tools.",
            parameters: Type.Object({}),
            async execute(_id, _p) {
                return tr(await run("setup", [], QUICK_TIMEOUT_MS));
            },
        });
        api.registerTool({
            name: "investorclaw_holdings",
            label: "Portfolio Holdings",
            description: "Get a portfolio snapshot with current prices for every holding in " +
                "master_portfolio.csv. Fetches live quotes via Finnhub → Massive → " +
                "Alpha Vantage → yfinance (first available). Returns JSON saved to " +
                "portfolio_reports/holdings.json.",
            parameters: Type.Object({}),
            async execute(_id, _p) {
                return tr(await run("holdings"));
            },
        });
        api.registerTool({
            name: "investorclaw_performance",
            label: "Portfolio Performance",
            description: "Analyze portfolio performance: YTD and 12-month returns, Sharpe ratio, " +
                "beta, volatility, max drawdown. Requires holdings.json from " +
                "investorclaw_holdings. Returns JSON saved to portfolio_reports/performance.json.",
            parameters: Type.Object({}),
            async execute(_id, _p) {
                return tr(await run("performance"));
            },
        });
        api.registerTool({
            name: "investorclaw_analysis",
            label: "Portfolio Analysis",
            description: "Run a full portfolio analysis combining the holdings snapshot with " +
                "performance metrics. Requires holdings.json from investorclaw_holdings. " +
                "Returns JSON saved to portfolio_reports/portfolio_analysis.json.",
            parameters: Type.Object({}),
            async execute(_id, _p) {
                return tr(await run("analysis"));
            },
        });
        api.registerTool({
            name: "investorclaw_bonds",
            label: "Bond Analysis",
            description: "Analyze fixed-income holdings: exact YTM, modified duration, convexity, " +
                "tax-equivalent yield for munis, and benchmark spread vs. FRED live " +
                "Treasury/TIPS yield curve (falls back to April 2026 seeds if FRED_API_KEY " +
                "is absent). Returns JSON saved to portfolio_reports/bond_analysis.json.",
            parameters: Type.Object({}),
            async execute(_id, _p) {
                return tr(await run("bonds"));
            },
        });
        api.registerTool({
            name: "investorclaw_fixed_income",
            label: "Fixed Income Report",
            description: "Generate a fixed-income strategy report with yield curve positioning, " +
                "duration risk, and rebalancing recommendations. Returns JSON saved to " +
                "portfolio_reports/fixed_income_analysis.json.",
            parameters: Type.Object({}),
            async execute(_id, _p) {
                return tr(await run("fixed-income"));
            },
        });
        api.registerTool({
            name: "investorclaw_news",
            label: "Portfolio News",
            description: "Fetch and summarize recent news correlated to portfolio holdings. " +
                "Requires NEWSAPI_KEY and holdings.json from investorclaw_holdings. " +
                "Returns JSON saved to portfolio_reports/portfolio_news.json.",
            parameters: Type.Object({}),
            async execute(_id, _p) {
                return tr(await run("news"));
            },
        });
        api.registerTool({
            name: "investorclaw_analyst",
            label: "Analyst Ratings",
            description: "Get analyst consensus ratings and price targets for portfolio holdings. " +
                "Uses Finnhub and/or Massive. Requires holdings.json from " +
                "investorclaw_holdings. Returns JSON saved to portfolio_reports/analyst_data.json.",
            parameters: Type.Object({}),
            async execute(_id, _p) {
                return analystWithCards();
            },
        });
        api.registerTool({
            name: "investorclaw_report",
            label: "Export Report",
            description: "Export portfolio data to CSV or Excel. Requires holdings.json from " +
                "investorclaw_holdings. Returns the path of the generated report file.",
            parameters: Type.Object({
                format: Type.Optional(Type.Union([Type.Literal("csv"), Type.Literal("excel")], { description: "Export format. Defaults to csv." })),
            }),
            async execute(_id, params) {
                const cmd = params.format === "excel" ? "excel" : "csv";
                return tr(await run(cmd));
            },
        });
        api.registerTool({
            name: "investorclaw_session",
            label: "Risk Session",
            description: "Initialize a risk-calibration session before running analysis. Sets a " +
                "heat level (1 = very conservative … 10 = aggressive) and optional macro " +
                "concerns that bias the guardrail messaging for the session.",
            parameters: Type.Object({
                heat_level: Type.Optional(Type.Integer({
                    minimum: 1,
                    maximum: 10,
                    description: "Risk tolerance: 1 = very conservative, 10 = aggressive.",
                })),
                concerns: Type.Optional(Type.String({
                    description: "Comma-separated macro concerns, e.g. 'inflation,rates,recession'.",
                })),
            }),
            async execute(_id, params) {
                const args = [];
                if (params.heat_level != null)
                    args.push("--heat-level", String(params.heat_level));
                if (params.concerns)
                    args.push("--concerns", params.concerns);
                return tr(await run("session", args, QUICK_TIMEOUT_MS));
            },
        });
        api.registerTool({
            name: "investorclaw_lookup",
            label: "Symbol Lookup",
            description: "Look up detailed data for a specific ticker symbol from cached .raw/ files " +
                "(holdings, analyst, or news data). Faster than re-running a full command " +
                "when only one symbol is needed.",
            parameters: Type.Object({
                symbol: Type.String({ description: "Ticker symbol, e.g. MSFT" }),
                file: Type.Optional(Type.Union([
                    Type.Literal("holdings"),
                    Type.Literal("analyst"),
                    Type.Literal("news"),
                ], { description: "Which dataset to query. Defaults to holdings." })),
            }),
            async execute(_id, params) {
                const args = ["--symbol", params.symbol.toUpperCase()];
                if (params.file)
                    args.push("--file", params.file);
                return tr(await run("lookup", args, QUICK_TIMEOUT_MS));
            },
        });
        api.registerTool({
            name: "investorclaw_ollama_setup",
            label: "Ollama Setup",
            description: "Check Ollama endpoint availability and list models suitable for " +
                "InvestorClaw consultation (tier-3 enrichment). Use this to verify the " +
                "local LLM setup before enabling INVESTORCLAW_CONSULTATION_ENABLED.",
            parameters: Type.Object({}),
            async execute(_id, _p) {
                return tr(await run("ollama-setup", [], QUICK_TIMEOUT_MS));
            },
        });
        api.registerTool({
            name: "investorclaw_guardrails",
            label: "Guardrails",
            description: "Inspect or interact with InvestorClaw's financial-advice guardrails. " +
                "'status' reports current enforcement state. 'prime' injects the " +
                "educational disclaimer preamble into the session. 'query' runs a " +
                "financial question through per-turn guardrail injection.",
            parameters: Type.Object({
                action: Type.Optional(Type.Union([Type.Literal("status"), Type.Literal("prime")], {
                    description: "'status' — show enforcement state. " +
                        "'prime' — inject calibration preamble. " +
                        "Omit to run a plain guardrail check.",
                })),
                query: Type.Optional(Type.String({
                    description: "Financial question to run through per-turn guardrail injection.",
                })),
            }),
            async execute(_id, params) {
                const args = [];
                if (params.action === "prime")
                    args.push("--prime");
                if (params.query)
                    args.push("--query", params.query);
                return tr(await run("guardrails", args, QUICK_TIMEOUT_MS));
            },
        });
    },
});
//# sourceMappingURL=index.js.map