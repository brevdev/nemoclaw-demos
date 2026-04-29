#!/usr/bin/env node
// One-time OAuth2 setup for Google Workspace APIs.
// Run on the host: node ./gmail-oauth-setup.js
//
// Prerequisites:
//   1. Go to https://console.cloud.google.com
//   2. Create a project (or select existing)
//   3. Enable APIs: APIs & Services → Library → enable Gmail, Calendar, Drive, Docs, Sheets, People, Tasks APIs
//   4. Create OAuth credentials: APIs & Services → Credentials → Create Credentials → OAuth client ID
//      - Application type: Desktop app
//      - Copy client_id and client_secret
//   5. Configure OAuth consent screen: APIs & Services → OAuth consent screen
//      - Add scopes: mail.google.com, calendar, drive, documents, spreadsheets, contacts.readonly, tasks
//      - Add your Gmail address as a test user
//   6. Run this script with your client_id and client_secret

const http = require("http");
const https = require("https");
const { URL } = require("url");
const fs = require("fs");
const path = require("path");
const readline = require("readline");

const CREDS_PATH = path.join(process.env.HOME, ".nemoclaw", "credentials.json");
const SCOPES = [
  "https://mail.google.com/",
  "https://www.googleapis.com/auth/calendar",
  "https://www.googleapis.com/auth/drive",
  "https://www.googleapis.com/auth/documents",
  "https://www.googleapis.com/auth/spreadsheets",
  "https://www.googleapis.com/auth/contacts.readonly",
  "https://www.googleapis.com/auth/tasks",
].join(" ");
const REDIRECT_URI = "http://localhost:3000/callback";

function ask(question) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => rl.question(question, (answer) => { rl.close(); resolve(answer.trim()); }));
}

function httpsPost(urlStr, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlStr);
    const data = typeof body === "string" ? body : new URLSearchParams(body).toString();
    const req = https.request({
      hostname: url.hostname, port: 443, path: url.pathname,
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "Content-Length": Buffer.byteLength(data) },
    }, (res) => {
      let buf = "";
      res.on("data", (d) => (buf += d));
      res.on("end", () => resolve({ status: res.statusCode, body: buf }));
    });
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

async function main() {
  console.log("\n  Google OAuth2 Setup for NemoClaw (Gmail + Calendar + Drive + Docs + Sheets + Contacts + Tasks)\n");

  let creds = {};
  try { creds = JSON.parse(fs.readFileSync(CREDS_PATH, "utf8")); } catch {}

  const clientId = creds.GOOGLE_CLIENT_ID || creds.GMAIL_CLIENT_ID || await ask("  Google OAuth Client ID: ");
  const clientSecret = creds.GOOGLE_CLIENT_SECRET || creds.GMAIL_CLIENT_SECRET || await ask("  Google OAuth Client Secret: ");

  if (!clientId || !clientSecret) {
    console.error("  Client ID and Secret are required.");
    process.exit(1);
  }

  const authUrl = `https://accounts.google.com/o/oauth2/v2/auth?` +
    `client_id=${encodeURIComponent(clientId)}` +
    `&redirect_uri=${encodeURIComponent(REDIRECT_URI)}` +
    `&response_type=code` +
    `&scope=${encodeURIComponent(SCOPES)}` +
    `&access_type=offline` +
    `&prompt=consent`;

  console.log("\n  Open this URL in your browser:\n");
  console.log(`  ${authUrl}\n`);
  console.log("  Waiting for callback on http://localhost:3000 ...\n");

  const code = await new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, "http://localhost:3000");
      if (url.pathname === "/callback") {
        const authCode = url.searchParams.get("code");
        const error = url.searchParams.get("error");
        if (error) {
          res.writeHead(400, { "Content-Type": "text/html" });
          res.end(`<h2>Error: ${error}</h2><p>Close this tab and try again.</p>`);
          reject(new Error(error));
        } else {
          res.writeHead(200, { "Content-Type": "text/html" });
          res.end("<h2>Success!</h2><p>You can close this tab and return to the terminal.</p>");
          resolve(authCode);
        }
        setTimeout(() => server.close(), 500);
      }
    });
    server.listen(3000);
    server.on("error", (e) => {
      if (e.code === "EADDRINUSE") {
        console.error("  Port 3000 is in use. Stop whatever is using it and try again.");
      }
      reject(e);
    });
  });

  console.log("  Authorization code received. Exchanging for tokens...\n");

  const tokenResp = await httpsPost("https://oauth2.googleapis.com/token", {
    code, client_id: clientId, client_secret: clientSecret,
    redirect_uri: REDIRECT_URI, grant_type: "authorization_code",
  });

  const tokens = JSON.parse(tokenResp.body);
  if (!tokens.refresh_token) {
    console.error("  Failed to get refresh token:", tokenResp.body);
    process.exit(1);
  }

  creds.GOOGLE_CLIENT_ID = clientId;
  creds.GOOGLE_CLIENT_SECRET = clientSecret;
  creds.GOOGLE_REFRESH_TOKEN = tokens.refresh_token;

  fs.writeFileSync(CREDS_PATH, JSON.stringify(creds, null, 2) + "\n");
  console.log(`  Saved to ${CREDS_PATH}`);
  console.log("\n  Google OAuth2 setup complete (Gmail + Calendar + Drive + Docs + Sheets + Contacts + Tasks). Credentials:");
  console.log(`    GOOGLE_CLIENT_ID:      ${clientId.substring(0, 20)}...`);
  console.log(`    GOOGLE_CLIENT_SECRET:  ${clientSecret.substring(0, 8)}...`);
  console.log(`    GOOGLE_REFRESH_TOKEN:  ${tokens.refresh_token.substring(0, 20)}...`);
  console.log("\n  You can now run ./install.sh to deploy the integration.\n");
}

main().catch((e) => { console.error("Error:", e.message); process.exit(1); });
