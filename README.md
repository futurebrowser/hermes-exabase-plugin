# Exabase M-1 Memory Plugin for Hermes Agent

Exabase M-1 memory-provider integration for Hermes Agent.

## About

[Exabase Memory (M-1)](https://exabase.io/memory) is a self-organising memory
engine for AI agents. It stores facts, preferences, and events, builds a living
knowledge graph, resolves contradictions, and evolves with every interaction.

M-1 is SOTA on the leading AI memory benchmark (LongMemEval), with the highest
recorded QA score, and using a small model. Read the research paper
[here](https://exabase.io/research/exabase-achieves-state-of-the-art-on-longmemeval-benchmark).


| System | Model | Score |
| --- | --- | --- |
| M-1 (Exabase) | Gemini 3 Flash | 96.4% |
| Mem0 | Gemini 3 Pro | 94.8% |
| Honcho | Gemini 3 Pro | 92.6% |
| HydraDB | Gemini 3 Pro | 90.79% |
| Supermemory | Gemini 3 Pro | 85.2% |

Exabase Memory powers memory in production apps like
[Fabric](https://fabric.so), used by 300,000+ people.

## What it does

This plugin adds support for Exabase M-1 long-term memory provider to Hermes
Agent. It allows agents to store conversation turns and inferred memories in
Exabase, and provide context for future interactions.

## Installation

Install the plugin from this repository and enable it in your Hermes Agent
configuration:

```bash
hermes plugins install git@github.com:futurebrowser/hermes-exabase-plugin.git
hermes memory setup  # choose 'exabase'
```

Choose `exabase` as the memory provider when prompted and enter your Exabase
API key.

## Configuration

The plugin can be configured with optional parameters that control how memories
are stored and retrieved.

- **Base ID**: The Exabase Base used for storing memories. This lets you scope
  memories and separate them by project, agent, or any other criteria. If not
  provided, no scoping will be used and memories will be stored in the default
  base.

- **Precision**: Controls the precision of memory retrieval. Higher precision
  means only the most relevant memories will be retrieved, while lower
  precision allows for more memories.

- **Query expansion**: Enabling query expansion allows the plugin to expand
  search queries with related terms, which broadens the search space and may
  help find more relevant memories at the cost of speed and Exabase credits.

- **Result reranking**: Uses an additional round of processing to rerank
  retrieved memories based on relevance to the query. This may improve the
  ranking of relevant memories at the cost of speed and Exabase credits.

## Tools

- `exabase_search` searches long-term memories.
- `exabase_remember` stores a memory.

Completed conversation turns are sent to Exabase in the background for inferred
memory extraction.
