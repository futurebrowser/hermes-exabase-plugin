# Exabase M-1 Memory Plugin for Hermes Agent

Exabase M-1 memory-provider integration for Hermes Agent.

## What it does

This plugin adds support for Exabase M-1 long-term memory provider to Hermes
Agent. It allows agents to store conversation turns and inferred memories in
Exabase, and provide context for future interactions.

## Installation

Clone this repository, drop it in your user-plugins folder, and enable it:

```bash
git clone https://github.com/futurebrowser/hermes-exabase-plugin.git
mkdir -p ~/.hermes/plugins && cp -r hermes-exabase-plugin ~/.hermes/plugins/exabase
hermes memory setup
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
