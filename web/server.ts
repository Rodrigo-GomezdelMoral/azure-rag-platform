import { readFile } from "node:fs/promises";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { extname, join, normalize } from "node:path";
import { Readable } from "node:stream";
import type { ReadableStream } from "node:stream/web";
import { fileURLToPath } from "node:url";
import { DefaultAzureCredential } from "@azure/identity";

const port = Number(process.env.PORT ?? 8080);
const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const audience = process.env.API_AUDIENCE;
const dist = fileURLToPath(new URL("./dist/", import.meta.url));
const credential = audience ? new DefaultAzureCredential() : null;
const types: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
};
let cached: { token: string; expiresOnTimestamp: number } | null = null;

async function bearer(): Promise<string | null> {
  if (!credential) return null;
  if (!cached || cached.expiresOnTimestamp - Date.now() < 60_000) {
    const fresh = await credential.getToken(`${audience}/.default`);
    cached = { token: fresh.token, expiresOnTimestamp: fresh.expiresOnTimestamp };
  }
  return cached.token;
}

function body(req: IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
  });
}

async function proxy(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const token = await bearer();
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token) headers.authorization = `Bearer ${token}`;
  const payload = req.method === "POST" ? await body(req) : undefined;
  const upstream = await fetch(apiBase + req.url, { method: req.method, headers, body: payload });
  const contentType = upstream.headers.get("content-type") ?? "application/json";
  res.writeHead(upstream.status, { "content-type": contentType, "cache-control": "no-store" });
  if (upstream.body) Readable.fromWeb(upstream.body as ReadableStream).pipe(res);
  else res.end();
}

async function serve(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const path = (req.url ?? "/").split("?")[0] ?? "/";
  if (path === "/healthz") {
    res.writeHead(200, { "content-type": "application/json" });
    return void res.end('{"status":"ok"}');
  }
  if (path.startsWith("/v1/")) return proxy(req, res);
  const file = normalize(join(dist, path === "/" ? "index.html" : path));
  if (!file.startsWith(dist)) {
    res.writeHead(403);
    return void res.end();
  }
  const data = await readFile(file).catch(() => readFile(join(dist, "index.html")));
  res.writeHead(200, { "content-type": types[extname(file)] ?? types[".html"] });
  res.end(data);
}

createServer((req, res) => {
  serve(req, res).catch((error: unknown) => {
    res.writeHead(502, { "content-type": "application/problem+json" });
    res.end(JSON.stringify({ title: "upstream failure", status: 502, detail: String(error) }));
  });
}).listen(port, () => console.log(`web listening on ${port}, api ${apiBase}, identity ${audience ? "on" : "off"}`));
