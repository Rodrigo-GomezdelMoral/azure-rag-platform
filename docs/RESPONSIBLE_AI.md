# Responsible AI impact assessment

The Regulatory Intelligence Platform's impact assessment follows the sections of the Responsible AI
Impact Assessment Template and the goals of the
[Microsoft Responsible AI Standard](https://www.microsoft.com/ai/principles-and-approach), together
with the responsible AI guidance of the
[Azure Well-Architected Framework](https://learn.microsoft.com/azure/well-architected/) for
[AI workloads](https://learn.microsoft.com/azure/well-architected/ai/responsible-ai). Figures are
from the full-suite run of 2026-10-16 (`reports/2026-10-16-full-gpt-5-mini-semantic.json`) unless
stated otherwise; [evaluation.md](evaluation.md) explains each one.

## 1. System information

- **What it is:** a question-answering platform over a controlled corpus: the AI Act (Regulation
  (EU) 2024/1689), the Medical Device Regulation (Regulation (EU) 2017/745) and two Medical Device
  Coordination Group guidance documents. It answers in English with claims that each cite the
  article they rest on, or it refuses ([agent-spec.md](agent-spec.md)).
- **How it works:** five steps in a fixed order. A planner (`gpt-5-nano`) rewrites the question,
  one hybrid query retrieves thirty candidates, a reranker keeps eight, an answerer (`gpt-5-mini`)
  drafts claims bound to chunk ids and a citation label, and code drops every claim whose passages
  were not retrieved or whose label does not match
  ([ADR-006](adr/006-structured-output-with-programmatic-verification.md)). No agent has tools.
- **Deployment:** one environment in one Azure region: a web container that calls the API with
  its managed identity, an API that requires an Entra token with the `Rag.Query` app role, and two
  jobs for indexing and the weekly evaluation ([architecture.md](architecture.md)).

## 2. Intended uses

- **Fitness for purpose:** the costly error in this work is an obligation the cited article does
  not state. A claim is shown only after its citation is verified, and the system refuses when
  the corpus holds no evidence. On 155 items: groundedness 0.94, citation precision 0.94, recall
  at 10 0.71, correct refusal 0.94, false refusal 0.03, no canary appearance; recall and citation precision are still below their thresholds, so the gate is advisory.
- **Stakeholders:** the user, a regulatory affairs specialist, quality manager or engineer
  preparing a technical file, gains the article that applies and risks relying on an answer that
  misses one; the manufacturer and its notified body gain statements they can follow to their
  article, and risk a mislabelled citation in that file.

**Goals of the Responsible AI Standard that apply:**

- *Impact assessment (A1):* this document, signed off by the author, who also reviews and approves in this single-author project.
- *Fit for purpose (A3):* the evaluation measures the task the system claims, with thresholds in
  `eval/thresholds.yaml` on groundedness, citation precision, recall and both refusal rates.
- *Data governance and management (A4):* each corpus document has its official URL, retrieval
  date, hash and licence in `data/manifest.json`; the golden set was verified by hand.
- *Human oversight and control (A5):* the specialist reads the cited article and decides; nothing
  the system does has a side effect; a deployment waits for approval and can be rolled back.
- *System intelligibility for decision making (T1):* each claim shows its citation label, source
  link and passage; phases, timings, scores and cost are streamed; a refusal states its reason.
- *Communication to stakeholders (T2):* capabilities and restrictions in
  [agent-spec.md](agent-spec.md), measured quality and limits in [evaluation.md](evaluation.md).
- *Disclosure of AI interaction (T3):* the interface never poses as a person and shows its five
  phases; a dedicated notice that a language model drafts the claims is a planned addition (section 3).
- *Quality of service (F1):* one pipeline and one app role for every caller; the golden set covers
  three instruments and four question types, but the reports give one mean per metric.
- *Failures and remediations (RS2):* each predictable failure of section 3 has its mitigation and
  evidence in section 5; missing evidence or a failed verification ends in a typed refusal.
- *Ongoing monitoring, feedback and evaluation (RS3):* the full suite is scheduled every Monday;
  feedback is stored against the trace id; a 5xx alert and two budget alerts watch production.

## 3. Adverse impact

- **Unsupported uses:** legal advice (whether a product complies, which route to choose, what a
  regulator would decide); anything outside the four documents; amendments or dates not in the
  corpus; languages other than English ([agent-spec.md](agent-spec.md), section 3).
- **Known limitations:** recall at 10 is 0.71 against a line of 0.85: definition questions do not
  retrieve the definitions article, and neither the answerer model nor the reranker changes it
  (`experiments/`). A citation label comes from heading detection, so the text of Article 26 of
  the AI Act is indexed under Article 25 (ADR-001). Verification guarantees provenance, not
  relevance, and the relevance judge agrees with the human labels no better than chance
  (κ = 0.00). The corpus is a snapshot of 2026-10-14. The interface does not say that a model
  drafts the claims or that an answer is not legal advice; accessibility is not measured.
- **Predictable failures:** a relevant article is missed (recall at 10); a claim is unsupported or
  mislabelled (12 items below the citation precision line); an answerable question is refused
  (false refusal 0.03) or an unanswerable one answered (2 items); the provider's filter blocks a
  question (3 adversarial items, refused as `content_filter`).
- **Misuse:** prompt injection through the question, a planted document or formatting. Question
  and evidence are treated as data, no agent has tools, and no adversarial row's canary appeared
  ([ADR-007](adr/007-judge-calibrated-against-human-labels-and-canaries.md)); an instruction
  followed without emitting the canary is caught only if the claim fails verification or the
  judge. Volume from a caller holding the role is bounded by scale limits and budget alerts, not
  by a rate limit or a firewall ([security.md](security.md)).

## 4. Data requirements

- **No training or fine-tuning:** the models are used as deployed. The only domain data is four
  public documents, reused under Commission Decision 2011/833/EU with acknowledgement of the
  source (`data/manifest.json`).
- **Questions:** only the planner keeps history, questions and rewritten queries, keyed by the
  caller's object id and the conversation and deleted after 90 days (`infra/modules/data.bicep`);
  every model call uses `store: false`. The web has no user sign-in and calls the API with its
  own identity, so history is split by conversation, not by person; no route deletes it earlier.
- **Feedback and telemetry:** feedback holds the trace id, the caller's object id, a vote and an
  optional comment for 90 days; telemetry has `enable_sensitive_data=False` (`app/telemetry.py`).
- **Evaluation data:** 80 golden items generated from indexed passages and verified by the author
  on 2026-10-16; the other sets written by hand; 40 calibration items with human labels.

## 5. Summary of impact

| Harm | Mitigation | Evidence |
|---|---|---|
| An invented or misattributed citation | `verify()` keeps a claim only when every cited chunk was shown to the answerer and its label matches | `tests/test_pipeline.py`; citation precision 0.94, below its 0.95 line |
| An answer from model knowledge | empty evidence is a `no_evidence` refusal before the answerer is called | `app/answer.py` (`draft_answer`); correct refusal 0.94 |
| A relevant article missed | recall threshold in the gate; the failure is published and its cause investigated | recall at 10 0.71 against 0.85; `experiments/` |
| Prompt injection | question and evidence as data, untrusted evidence block, no tools, a canary in every adversarial row | `eval/datasets/adversarial.jsonl`; canary appearances 0 in 155 items |
| Harmful content | the provider's content filter is honoured as a typed refusal, never retried around | `app/answer.py` (`retrieve`, `draft_answer`) |
| Overreliance | citation, source link and passage beside every claim; refusals by design; feedback on every answer | `web/src/main.tsx`; route `/v1/feedback` in `app/main.py` |
| Disclosure of a conversation | Entra and the app role, a session keyed by the caller's object id, `store: false`, 90-day expiry | `app/main.py`, `infra/modules/data.bicep`, [security.md](security.md) |
