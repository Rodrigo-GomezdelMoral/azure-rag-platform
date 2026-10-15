# ADR-001 · Integrated vectorisation, and what makes re-ingestion safe

**Status:** accepted · **Date:** 2026-10-14

## Context

The corpus is four official PDFs — two regulations and two guidance documents — that change a
few times a year: a corrigendum, a consolidated version, a revised guidance. Each change must
reach the index without duplicating chunks, without leaving stale chunks behind, and without a
person remembering which file changed. The index is also the only artefact whose quality the
evaluation harness measures, so the ingestion path has to be reproducible to the chunk.

Two things are being decided at once: who computes the chunks and embeddings, and how a changed
document replaces its old chunks.

## Options

1. **An ingestion script in this repository.** Download, parse the PDF with a Python library,
   split, call the embedding model, push documents to the index. Full control over chunking, and
   a few hundred lines to own, test and keep aligned with the model deployment, plus a cron job
   and a state file to make it incremental.
2. **Integrated vectorisation.** An indexer reads the blob container with the search service's
   identity, a skillset extracts layout, chunks and embeds, and an index projection writes one
   search document per chunk. Change detection, deletion detection, scheduling, retries and the
   embedding call are the service's; the repository owns a declarative definition.
3. **A managed ingestion product** (Foundry IQ knowledge bases). The least code, and the least
   visibility into chunk boundaries, scores and ids — which ADR-010 rejects for the same reason
   it rejects the context provider: this platform needs to show its retrieval.

## Decision

Option 2. `ops/index.py` creates four objects and nothing else runs at ingestion time:

| Object | What it declares |
|---|---|
| Data source | the `corpus` blob container, reached with the search service's **own managed identity** (`ResourceId=` connection string, no key), with native `LastModified` change detection and a soft-delete policy on the `isDeleted` blob metadata |
| Skillset | four skills. Document Layout in Markdown mode with a three-level heading depth, which emits one section per heading path. A Shaper that computes `citation_label` and `article` from that path with the skill annotation language — an expression, not code. Text Split in pages mode, 2,000 characters with 200 of overlap, run **inside each section**, so no chunk crosses a heading. The Azure OpenAI Embedding skill against the shared `text-embedding-3-small` deployment, authenticated by the same identity. Built-in skills are billed keylessly through the shared Foundry account |
| Index | one document per chunk: `content`, `content_vector`, `citation_label`, `article`, `regulation`, `language`, `source_url`, `parent_id` |
| Indexer | daily schedule, `allowSkillsetToReadFileData` with metadata-only extraction (the layout skill reads the file itself), one blob per batch so a failing document does not fail its neighbours |

### The label

Document Intelligence treats the title of a regulation as `h1`: in the AI Act, 75 of 137
sections sit under the 87-character instrument title, which the `regulation` field already
carries. The label therefore takes the two most specific levels — `h2 > h3`, or `h2`, or `h1`,
or the regulation code for front matter — and `article` takes the deepest non-empty level.
Short labels are not cosmetic: the answerer copies the label into every claim and the verifier
compares it character for character (ADR-006), so every character is a chance to fail
verification.

### What makes re-ingestion safe

- **Identity of a chunk.** The projection derives every key from the parent document key, the
  chunk's position in the enrichment tree (`sections/i/chunks/j`) and a version hash the service
  assigns to each parent version. Re-processing a changed blob issues a new version, writes its
  chunks and deletes the previous version's; the service, not this repository, guarantees that
  exactly one version of a document's chunks exists. The corollary is that a `chunk_id` is not
  durable across corpus versions: the durable provenance is `citation_label`, `source_url` and the
  manifest hash, which is why the golden set and the stored conversations refer to labels.
- **Identity of a document.** `ops/corpus.py` computes the SHA-256 of every download and writes
  it to `data/manifest.json` and to the blob's metadata. A download whose hash matches the stored
  blob is not uploaded, so the blob's `LastModified` does not move and the indexer does nothing.
  A different hash is a different document: it is uploaded, the indexer sees the new timestamp,
  and the chunks are rebuilt.
- **Deletion.** Setting the `isDeleted` metadata to `true` on a blob removes its chunks on the
  next run through the deletion policy; deleting the blob outright does not, which is why the
  policy exists and the README says to mark rather than delete.
- **Versioning.** The manifest records URL, retrieval date, hash, language and licence per
  document, so an evaluation report can state exactly which corpus it measured.

### Why there is no page number

The specification asked the layout skill for page numbers and heading hierarchy. The service
offers one or the other: `locationMetadata` is rejected with Markdown output ("supported value:
text"), and text output returns fixed windows with no heading at all — even with a Markdown
skill in the same skillset, contrary to the reference page — with paragraphs joined without a
separator (`processing.During`, `2024SECTION`) and windows that straddle two articles. A probe
over the AI Act and MDCG 2019-11 established this on 2026-10-14 before the design was fixed.
A citation that names the article is what a regulatory reader checks; a page number alone is
not. The index therefore carries the heading path and the source URL, and the Markdown content
keeps Document Intelligence's page comments (`<!-- PageNumber="57/144" -->`, `<!-- PageBreak -->`)
as they arrive: stripping them is code, the ranker and the embedding model are indifferent to
them, and they are the page evidence a reader has.

## Trade-offs

- Chunk boundaries are the service's. A section longer than 2,000 characters becomes several
  chunks that share a label; the AI Act recitals are a single 250,000-character section and
  become 145 chunks labelled with the instrument title, which is what they are.
- Heading detection is Document Intelligence's. In the AI Act some articles land on `h1`, most on
  `h2`, a few on `h3`; the label logic takes the deepest levels so an article survives whichever
  level it lands on, and a heading the model misses stays inside the previous section's content.
- The Document Layout skill is billed per page through the Foundry account; the four documents
  are about 390 pages, re-processed only when a hash changes.
- No incremental enrichment cache is configured, so a skillset change re-runs every skill on
  every document. At 390 pages that is minutes and cents; at a thousand documents it would be
  the first thing to add.

## Revisit when

Chunking quality measurably limits recall at 10 — the point at which a custom web skill or an
ingestion job earns its code — or the corpus grows past the size where re-running every skill on
a skillset change is acceptable.
