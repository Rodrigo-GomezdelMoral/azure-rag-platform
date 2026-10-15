# ADR-002 · Scalar quantisation and `stored: false`, with measured sizes

**Status:** accepted · **Date:** 2026-10-14

## Context

The index holds 1,010 chunks, each with a 1,536-dimensional float32 embedding. Left to its
defaults, the service keeps up to three copies of every vector: the copy stored with the
document and returned in results, the copy inside the HNSW graph that lives in memory and is
charged against the vector quota, and — once compression is on — the full-precision copy kept
for rescoring. The search service is the landing zone's shared Basic tier: 15 GB of storage and
5 GB of vector quota per partition, shared by every workload in the portfolio. The question is
which copies this index needs, and at what precision.

## Options

1. **float32, stored, uncompressed.** The simplest definition. Two copies of every vector, one
   of them returned to callers that never read it.
2. **Scalar quantisation to int8, rescoring on the originals, `stored: false`.** The graph holds
   int8 values, the originals stay on disk for rescoring, and the retrievable copy is gone.
3. **Binary quantisation with the originals discarded.** The smallest graph the service offers,
   recommended for more than 1,024 dimensions and for corpora where the quota binds. Recall
   loss would have to be measured here, and at this size there is nothing to gain from it.
4. **Dimension truncation.** `text-embedding-3-small` supports Matryoshka truncation, so 512
   dimensions with quantisation would shrink the graph again, at a recall cost no harness has
   measured yet.

## Decision

Option 2. No caller reads a vector — the API ranks by score and returns chunks — so the
retrievable copy is removed (`stored: false`, and the field is hidden). The graph is int8 with
`preserveOriginals` and the default oversampling of four, so the top candidates of every vector
query are rescored against full-precision values before they are merged with the keyword
results. Options 3 and 4 are the levers to pull when the quota, not the corpus, is the problem.

## Measurement

`python -m ops.index --uncompressed` builds a twin, `regulations-uncompressed`, from the same
skillset over the same four documents with float32 vectors, stored and uncompressed. Both
indexes were read with the index statistics endpoint on 2026-10-14 after the figures settled —
they lag indexing by several minutes — and the twin was deleted afterwards.

| Index | Chunks | Storage | Vector index (memory, counted against the quota) |
|---|---|---|---|
| `regulations` — int8, originals kept for rescoring, `stored: false` | 1,010 | 11,880,644 B | 1,996,004 B |
| `regulations-uncompressed` — float32, stored | 1,010 | 22,956,770 B | 6,266,420 B |

The arithmetic behind the figures: 1,010 vectors × 1,536 dimensions is 6,205,440 B at four
bytes per value and 1,551,360 B at one. The float32 values account for almost all of the
uncompressed graph; the int8 values account for most of the compressed one, the rest being the
structure around them. Measured end to end, the vector index is 3.1 times smaller and storage
1.9 times smaller. The documentation promises a fourfold reduction, which holds for the values
and not for the whole graph. Storage shrinks less than the graph for two reasons: the compressed
index keeps the float32 originals on disk for rescoring, and the twin stores every float32
vector twice — once in the document, once in the graph — while the chunk text is the same in
both.

## Trade-offs

- Rescoring reads the originals for four times `k` candidates on every vector query. At this
  size that is a few milliseconds; `search` timings are recorded per phase in the answer.
- `stored: false` is irreversible for the field and the originals are not readable through the
  API, so rebuilding the index means re-running the skillset and re-embedding every chunk —
  the same consequence ADR-001 accepts for a skillset change.
- Quantisation is lossy. Rescoring restores the order of the top candidates but not of the
  candidates oversampling missed; recall at 10 in the evaluation harness is measured on this
  index, so any loss shows up where it would matter.
- In absolute terms the saving is a few megabytes against a five-gigabyte quota. The decision is
  about the shape that scales: a thousand documents of this kind would be about a quarter of a
  million chunks, roughly 500 MB of int8 graph instead of 1.6 GB of float32.

## Revisit when

The vector index approaches the partition quota — binary quantisation and dimension truncation
are then measured against the uncompressed twin — or the evaluation harness reports recall at
10 below its threshold, in which case the twin is rebuilt and the two are compared on the same
golden set.
