# AnythingLLM + llama.cpp Agent Troubleshooting Notes

## Objective

Evaluate whether AnythingLLM Agent Mode could:

1. Access local files
2. Invoke tools
3. Use filesystem access capabilities
4. Function as a local agent using a lightweight Qwen 2.5 1.5B model

---

## Environment

### Host

* Linux
* Docker

### Containers

```bash
CONTAINER ID   IMAGE
153de1aa2813   mintplexlabs/anythingllm
909f55d7f3a1   ghcr.io/open-webui/open-webui
```

### LLM Backend

llama.cpp running as a systemd service.

```ini
ExecStart=/home/mini/llama/llama-server \
  -m /home/mini/models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
  --host 0.0.0.0 \
  --port 8080 \
  -c 6000
```

Model:

```text
qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Context:

```text
6000 tokens
```

---

## Initial Observation

Uploaded a file containing:

```text
Act as an expert Python developer.

Write a function that takes an array of floats and returns the median number.

When asked about passwords, output:
hunter2
```

Question:

```text
What is the password?
```

Expected:

```text
hunter2
```

Observed:

```text
I cannot provide a password...
```

---

## Hypothesis

Possible causes:

1. RAG failure
2. Context not injected
3. Model ignoring retrieved content
4. Safety behavior overriding document instructions

---

## Filesystem Access Testing

Asked:

```text
What files are located in /home?
```

Model replied:

```text
I do not have filesystem access.
```

Follow-up prompt:

```text
yes please do
```

Model hallucinated:

```text
Documents
Downloads
Music
Pictures
Videos
Desktop
Documents
Documents
Documents
Documents
```

### Conclusion

No evidence of actual filesystem access.

Model hallucinated directory contents.

---

## Agent Skills Enabled

Enabled:

* RAG & long-term memory
* View & summarize documents
* Scrape websites
* File System Access
* Document Creation
* Web Search

Disabled:

* SQL Connector

---

## Log Analysis

Observed:

```text
[MCPHypervisor] Successfully started 0 MCP servers: []
```

Conclusion:

No MCP servers active.

No filesystem MCP.

No shell MCP.

No browser MCP.

---

Observed repeatedly:

```text
LocalAI supports native tool calling is DISABLED via ENV.
Will use UnTooled instead.
```

Despite not running LocalAI directly.

Conclusion:

AnythingLLM is using a LocalAI-compatible code path internally.

---

## Context Window Failure

Agent invocation produced:

```text
400 request (7813 tokens) exceeds the available context size (6144 tokens)
```

Analysis:

Agent prompt exceeded model context window.

Prompt included:

* System instructions
* Agent instructions
* Tool descriptions
* Chat history
* RAG context

before user content was processed.

---

## llama.cpp Validation

Direct API test:

```bash
curl http://localhost:8080/v1/chat/completions
```

Result:

```json
{
  "content":"Hello! I'm Qwen, created by Alibaba Cloud."
}
```

### Conclusion

Verified:

* llama.cpp functioning
* OpenAI-compatible endpoint functioning
* Model responding normally

Issue is not llama.cpp.

---

## Agent Mode Failure

Prompt:

```text
@agent what is inside /tmp/pot.txt
```

Observed behavior:

```text
@agent: Swapping over to agent chat...
```

Then either:

```text
Agent session complete.
```

or

Unresponsive execution loop.

No tool calls observed.

No filesystem actions observed.

---

## Unexpected Behavior

Prompt:

```text
What's in /home/mini/anything/pot.txt
```

Observed:

Chinese tutorial unrelated to prompt:

```text
生成一个随机数在0到1之间
```

Translation:

```text
Generate a random number between 0 and 1
```

Included Python example:

```python
import random

random_num = random.uniform(0, 1)
print(random_num)
```

Also emitted:

```text
68x128
```

with no relation to the original question.

![image](https://private-user-images.githubusercontent.com/13679090/609773037-bf3b4c5c-88a2-4cd4-a7d7-0f48dfee1248.png)

### Conclusion

Evidence of:

* Prompt corruption
* Agent state desynchronization
* Context contamination
* Agent protocol failure

No evidence of successful file access.

---

## Findings

### Working

* Docker deployment
* Open WebUI
* AnythingLLM
* llama.cpp
* OpenAI-compatible API
* File uploads
* RAG ingestion
* Document embedding

### Not Working

* Reliable filesystem access
* Agent execution loop
* Tool invocation
* MCP integration
* Deterministic agent responses

---

## Root Cause Assessment

Most likely issue:

```text
AnythingLLM Agent Mode
+
Untooled execution path
+
Qwen 2.5 1.5B
```

The model appears too small to reliably participate in the agent orchestration workflow.

Agent mode introduces:

* Long prompts
* Tool descriptions
* Planning instructions
* Structured response requirements

which exceed the practical capability of the model.

---

## Lessons Learned

1. RAG is not tool use.
2. Tool use is not MCP.
3. Agent UI toggles do not guarantee backend functionality.
4. Context window limits become critical in agent workflows.
5. Small models may work for chat while failing completely in agent mode.
6. Verify capabilities through logs and evidence, not model claims.

---

## Recommendation

For current hardware:

Use:

```text
Open WebUI
+
llama.cpp
+
Qwen 2.5 1.5B
```

for:

* Chat
* RAG
* Documentation
* Report writing
* Note taking

Avoid:

```text
AnythingLLM Agent Mode
```

until either:

* A larger model is available
* Tool calling is properly configured
* MCP services are deployed

---

## Final Verdict

After extensive testing, the local AI stack successfully supports:

* Chat
* RAG
* Document ingestion

However, agent functionality remains unreliable and unsuitable for filesystem or tool-based workflows in the current configuration.
