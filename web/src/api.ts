export type Phase = "plan" | "search" | "rerank" | "answer" | "verify";
export type Refusal = "no_evidence" | "unverified" | "content_filter";
export const PHASES: Phase[] = ["plan", "search", "rerank", "answer", "verify"];

export interface Candidate {
  chunk_id: string;
  regulation: string;
  article: string;
  citation_label: string;
  hybrid_score: number;
  rerank_score: number | null;
  rank_delta: number | null;
  content?: string;
}

export interface Citation extends Candidate {
  content: string;
  source_url: string;
}

export interface Claim {
  text: string;
  chunk_ids: string[];
  citation_label: string;
}

export interface Answer {
  trace_id: string;
  claims: Claim[];
  citations: Citation[];
  refusal: Refusal | null;
  unverified_claims: number;
  cost_eur: number;
  timings_ms: Partial<Record<Phase, number>>;
}

export interface PhaseEvent {
  phase: Phase;
  trace_id: string;
  elapsed_ms: number;
  data: Record<string, unknown>;
}

interface Fixture {
  question: string;
  events: PhaseEvent[];
}

export const DEMO = import.meta.env.VITE_DEMO_MODE === "true";
const fixtures = Object.values(import.meta.glob<Fixture>("../fixtures/*.json", { eager: true, import: "default" }));
export const recorded = fixtures.map((fixture) => fixture.question);

export function candidates(events: PhaseEvent[], phase: "search" | "rerank"): Candidate[] {
  const event = events.find((item) => item.phase === phase);
  return (event?.data.candidates as Candidate[] | undefined) ?? [];
}

export function finalAnswer(events: PhaseEvent[]): Answer | null {
  const event = events.find((item) => item.phase === "verify");
  return event ? (event.data as unknown as Answer) : null;
}

async function describe(response: Response): Promise<string> {
  try {
    const problem = (await response.json()) as { title?: string; detail?: string; trace_id?: string };
    return `${problem.title ?? response.status}: ${problem.detail ?? ""} (trace ${problem.trace_id ?? "n/a"})`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

async function stream(body: object, onEvent: (event: PhaseEvent) => void, signal: AbortSignal): Promise<void> {
  const headers = { "content-type": "application/json" };
  const response = await fetch("/v1/answer", { method: "POST", headers, body: JSON.stringify(body), signal });
  if (!response.ok || !response.body) throw new Error(await describe(response));
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const data = frame.split("\n").find((line) => line.startsWith("data: "));
      if (data) onEvent(JSON.parse(data.slice(6)) as PhaseEvent);
    }
  }
}

const tokens = (text: string): Set<string> => new Set(text.toLowerCase().match(/[a-z0-9]+/g) ?? []);

function closest(question: string): Fixture | undefined {
  const wanted = tokens(question);
  const overlap = (fixture: Fixture) => [...tokens(fixture.question)].filter((token) => wanted.has(token)).length;
  return [...fixtures].sort((a, b) => overlap(b) - overlap(a))[0];
}

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => (clearTimeout(timer), reject(new DOMException("aborted", "AbortError"))), { once: true });
  });
}

async function replay(question: string, onEvent: (event: PhaseEvent) => void, signal: AbortSignal): Promise<void> {
  const fixture = closest(question);
  if (!fixture) throw new Error("no recorded run to replay");
  let previous = 0;
  for (const event of fixture.events) {
    await pause(Math.min((event.elapsed_ms - previous) * 0.5, 6000), signal);
    previous = event.elapsed_ms;
    onEvent(event);
  }
}

export function ask(question: string, conversationId: string, onEvent: (event: PhaseEvent) => void, signal: AbortSignal) {
  return DEMO ? replay(question, onEvent, signal) : stream({ question, conversation_id: conversationId }, onEvent, signal);
}

export async function sendFeedback(traceId: string, helpful: boolean): Promise<void> {
  if (DEMO) return;
  const body = JSON.stringify({ trace_id: traceId, helpful });
  await fetch("/v1/feedback", { method: "POST", headers: { "content-type": "application/json" }, body });
}
