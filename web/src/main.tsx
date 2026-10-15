import { StrictMode, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { type Answer, type Candidate, type Phase, type PhaseEvent, type Refusal, DEMO, PHASES, ask, candidates, finalAnswer, recorded, sendFeedback } from "./api";

const SCOPES: [string, string][] = [
  ["", "Any instrument"],
  ["under the AI Act", "AI Act"],
  ["under the MDR", "MDR"],
  ["according to MDCG 2019-11", "MDCG 2019-11"],
  ["according to MDCG 2020-1", "MDCG 2020-1"],
];
const REFUSALS: Record<Refusal, string> = {
  no_evidence: "Retrieval returned nothing the answerer could use, so no claim was written. The corpus does not support an answer to this question.",
  unverified: "Every drafted claim failed verification: a cited passage was not among the retrieved ones or its label did not match. The answer was withheld rather than shown unverified.",
  content_filter: "The model provider's content filter refused this request.",
};
const money = (eur: number) => `€${eur.toFixed(4)}`;
const score = (value: number | null | undefined, digits = 2) => (value == null ? "—" : value.toFixed(digits));

function summary(event: PhaseEvent | undefined, answer: Answer | null): string {
  if (!event) return "";
  const data = event.data;
  switch (event.phase) {
    case "plan":
      return `→ ${String(data.query)}`;
    case "search":
      return `${(data.candidates as Candidate[]).length} candidates from one hybrid query`;
    case "rerank":
      return `${(data.candidates as Candidate[]).length} kept · ${String(data.reranker)} reranker`;
    case "answer":
      return `${String(data.claims)} claims drafted`;
    case "verify":
      return answer?.refusal ? `refused: ${answer.refusal}` : `${answer?.claims.length ?? 0} verified · ${answer?.unverified_claims ?? 0} dropped`;
  }
}

function Timeline({ events, running, answer }: { events: PhaseEvent[]; running: boolean; answer: Answer | null }) {
  const done = new Map(events.map((event) => [event.phase, event]));
  const current = PHASES[events.length];
  return (
    <section>
      <h2>Pipeline</h2>
      <ol className="timeline">
        {PHASES.map((phase) => {
          const event = done.get(phase);
          const state = event ? "done" : running && phase === current ? "running" : "pending";
          return (
            <li key={phase} className={state}>
              <span className="name">{phase}</span>
              {event && <span className="ms">{event.elapsed_ms} ms</span>}
              <div className="summary">{state === "running" ? "…" : summary(event, answer)}</div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function AnswerPanel({ answer }: { answer: Answer }) {
  const [sent, setSent] = useState<boolean | null>(null);
  const index = new Map(answer.citations.map((citation, position) => [citation.chunk_id, position + 1]));
  if (answer.refusal) {
    return (
      <section className="refusal">
        <h2>Refused · {answer.refusal.replace("_", " ")}</h2>
        <strong>The platform did not answer, by design.</strong>
        <p>{REFUSALS[answer.refusal]}</p>
        <p className="feedback">Trace {answer.trace_id} · {answer.unverified_claims} claim(s) dropped · {money(answer.cost_eur)}</p>
      </section>
    );
  }
  const vote = (helpful: boolean) => void sendFeedback(answer.trace_id, helpful).then(() => setSent(helpful));
  return (
    <section>
      <h2>Answer · {answer.claims.length} verified claims</h2>
      {answer.claims.map((claim, position) => (
        <p className="claim" key={position}>
          {claim.text}
          {claim.chunk_ids.map((chunkId) => (
            <sup key={chunkId}>
              <a href={`#citation-${index.get(chunkId)}`}>[{index.get(chunkId)}]</a>
            </sup>
          ))}
        </p>
      ))}
      <div className="feedback row">
        <span>Was this answer useful?</span>
        <button className="quiet" disabled={sent !== null} onClick={() => vote(true)}>Yes</button>
        <button className="quiet" disabled={sent !== null} onClick={() => vote(false)}>No</button>
        {sent !== null && <span>Recorded against trace {answer.trace_id}.</span>}
      </div>
    </section>
  );
}

function Citations({ answer }: { answer: Answer }) {
  if (!answer.citations.length) return null;
  return (
    <section>
      <h2>Citations</h2>
      {answer.citations.map((citation, position) => (
        <div className="citation" id={`citation-${position + 1}`} key={citation.chunk_id}>
          <span className="label">[{position + 1}] {citation.citation_label}</span>
          <div className="meta">
            {citation.regulation} · <a href={citation.source_url} target="_blank" rel="noreferrer">source document</a>
          </div>
          <details>
            <summary>Passage</summary>
            <blockquote>{citation.content}</blockquote>
          </details>
        </div>
      ))}
    </section>
  );
}

function Debug({ events, question, answer }: { events: PhaseEvent[]; question: string; answer: Answer | null }) {
  const plan = events.find((event) => event.phase === "plan");
  const kept = new Map(candidates(events, "rerank").map((candidate, position) => [candidate.chunk_id, { position, candidate }]));
  const timings: [Phase, number][] = PHASES.flatMap((phase) => {
    const value = answer?.timings_ms[phase];
    return value == null ? [] : [[phase, value]];
  });
  return (
    <aside>
      <h2>Retrieval</h2>
      <dl>
        <dt>Asked</dt>
        <dd>{question}</dd>
        <dt>Rewritten</dt>
        <dd>{plan ? String(plan.data.query) : "—"}</dd>
        <dt>Filters</dt>
        <dd><code>{plan ? JSON.stringify(plan.data.filters) : "—"}</code></dd>
        <dt>Trace</dt>
        <dd><code>{events[0]?.trace_id ?? "—"}</code></dd>
      </dl>
      <h2 style={{ marginTop: 14 }}>Candidates</h2>
      <table>
        <thead>
          <tr><th>#</th><th>Citation label</th><th className="num">Hybrid</th><th className="num">Rerank</th><th className="num">Δ rank</th></tr>
        </thead>
        <tbody>
          {candidates(events, "search").map((candidate, position) => {
            const entry = kept.get(candidate.chunk_id);
            const delta = entry?.candidate.rank_delta ?? null;
            return (
              <tr key={candidate.chunk_id} className={entry ? "kept" : ""}>
                <td className="num">{position + 1}</td>
                <td>{candidate.citation_label} <span className="meta">· {candidate.regulation}</span></td>
                <td className="num">{score(candidate.hybrid_score, 4)}</td>
                <td className="num">{score(entry?.candidate.rerank_score ?? candidate.rerank_score)}</td>
                <td className={`num delta ${delta == null ? "" : delta > 0 ? "up" : delta < 0 ? "down" : ""}`}>
                  {delta == null ? "—" : delta > 0 ? `+${delta}` : String(delta)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {answer && (
        <>
          <h2 style={{ marginTop: 14 }}>Timings and cost</h2>
          <dl>
            {timings.map(([phase, ms]) => (
              <span key={phase} style={{ display: "contents" }}>
                <dt>{phase}</dt>
                <dd>{ms} ms</dd>
              </span>
            ))}
            <dt>Total</dt>
            <dd>{timings.reduce((sum, [, ms]) => sum + ms, 0)} ms</dd>
            <dt>Cost</dt>
            <dd>{money(answer.cost_eur)} (planner, reranker when used, answerer)</dd>
          </dl>
        </>
      )}
    </aside>
  );
}

function App() {
  const [question, setQuestion] = useState("");
  const [scope, setScope] = useState("");
  const [article, setArticle] = useState("");
  const [events, setEvents] = useState<PhaseEvent[]>([]);
  const [asked, setAsked] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [inspect, setInspect] = useState(false);
  const [conversation, setConversation] = useState(() => crypto.randomUUID());
  const controller = useRef<AbortController | null>(null);
  const answer = finalAnswer(events);

  async function submit(text: string) {
    const composed = [text.trim(), scope && `(${scope})`, article && `(${article})`].filter(Boolean).join(" ");
    if (!composed || running) return;
    controller.current?.abort();
    controller.current = new AbortController();
    setAsked(composed);
    setEvents([]);
    setError("");
    setRunning(true);
    try {
      await ask(composed, conversation, (event) => setEvents((previous) => [...previous, event]), controller.current.signal);
    } catch (failure) {
      if (!(failure instanceof DOMException && failure.name === "AbortError")) setError(String(failure));
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <header>
        <h1>Regulatory Intelligence Platform</h1>
        <p>Grounded answers over the EU AI Act, the MDR and MDCG guidance. Every claim cites the article it rests on, or the platform refuses.</p>
      </header>
      <main className={inspect ? "inspecting" : ""}>
        <section>
          <form className="bar" onSubmit={(event) => (event.preventDefault(), submit(question))}>
            <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about an obligation, a definition, a procedure or how two instruments interact" />
            <select value={scope} onChange={(event) => setScope(event.target.value)} disabled={DEMO} title="Scope">
              {SCOPES.map(([value, label]) => <option key={label} value={value}>{label}</option>)}
            </select>
            <input className="article" value={article} onChange={(event) => setArticle(event.target.value)} placeholder="Article 9" disabled={DEMO} />
            <button type="submit" disabled={running}>{running ? "Working…" : "Ask"}</button>
            <button type="button" className="quiet" onClick={() => (setConversation(crypto.randomUUID()), setEvents([]), setQuestion(""))}>New conversation</button>
          </form>
          {DEMO && (
            <>
              <div className="banner">Demo mode: recorded runs are replayed with their real phase timings halved. No backend is called.</div>
              <div className="chips">
                {recorded.map((text) => <button key={text} type="button" onClick={() => (setQuestion(text), submit(text))}>{text}</button>)}
              </div>
            </>
          )}
          {error && <div className="error">{error}</div>}
          <div className="row" style={{ marginTop: 10 }}>
            <label><input type="checkbox" checked={inspect} onChange={(event) => setInspect(event.target.checked)} /> Inspect retrieval</label>
            <span className="feedback" style={{ margin: 0 }}>Conversation {conversation.slice(0, 8)}</span>
          </div>
        </section>
        {(events.length > 0 || running) && <Timeline events={events} running={running} answer={answer} />}
        {answer && <AnswerPanel answer={answer} key={answer.trace_id} />}
        {answer && <Citations answer={answer} />}
        {inspect && events.length > 0 && <Debug events={events} question={asked} answer={answer} />}
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
