# CV/CL review model — 2026-10-09

Updated 2026-10-10: the default Python review and annotation-dialogue route tries
`litellm-gateway:review-strong-glm53-key1` through `review-strong-glm53-key7`,
in that order. Each alias uses one existing NVIDIA key for NIM's `z-ai/glm-5.3`,
with `extra_body.reasoning_effort: low`. The original pooled alias
`review-strong-glm53` remains available for compatibility. No accounts, keys or
subscriptions were added.

Each key gets one attempt. A provider error or unusable review advances to the
next available key; the default chain never changes to a weaker model. If all
keys fail, the request fails before the existing review is archived or replaced.
`REVIEW_FALLBACKS` still accepts an explicitly chosen provider/model sequence.
Other aliases, their fallback chains and global Gateway router settings are
preserved. NVIDIA keys share quota across aliases;
the configured per-deployment `rpm: 1` and `tpm: 32000` are routing capacity
metadata, not verified hard isolation from other workloads.

`run_review` now supplies the complete CV/CL. The previous 7,000-character
cutoff hid tail sections and led to false claims that education/languages were
missing. Existing reviews are retained; changing the model does not trigger
mass regeneration or invalidate unchanged documents.

The new alias uses streamed HTTP reception internally. The entire text is
buffered before it reaches the reviewer; reasoning tokens are excluded. The
client requires a normal `stop` finish and `[DONE]`, closes the connection, and
rejects interruptions, token limits, malformed frames and empty content. This
route has no repeated client or Gateway retry on the same key. Its outer review
chain advances to the next key on failure. Its read inactivity budget
is 90 seconds and its overall stream budget is 300 seconds, checked when a line
arrives. A blocking read can therefore exceed the overall budget by up to its
inactivity timeout. Legacy aliases retain their existing request behavior.

During deployment, a non-streaming full review timed out at 300 seconds. A
second Gateway attempt returned 408 at 150 seconds, and a direct upstream
attempt timed out at 180 seconds. The same 100,071-character prompt completed
through the Gateway in streaming mode in 63.945 seconds; first text arrived
after 11.306 seconds, with a normal stop, `[DONE]`, and a usable CV review.
This demonstrates a working reception path, not guaranteed future availability
or a proven root cause for the non-streaming failures.

Validation includes the full document tail, strict default routing, explicit
overrides, preservation of an existing review on failures, stream completion,
connection cleanup, interrupted/malformed/empty streams and the time budget.
The existing review, provider dispatch and timeout tests are included.

The key fallback reuses the existing provider-chain and quarantine mechanism.
Quarantine is scoped to `litellm-gateway:review-strong-glm53-keyN`: a 429 has a
15-minute cooldown, and a 401/402/403 or quota error has the existing 14-day
cooldown. These are local retry schedules, not NVIDIA quota-reset estimates.
Quarantined keys are skipped while another key is available; if every key is
quarantined, the existing chain policy allows one probe per key. Other Gateway
models retain their prior quarantine scope.

The pooled alias could not provide the promised failover: the request's
`num_retries: 0` overrode the Gateway retry setting, and its shuffled pool tried
only one key. Giving each key a separate alias makes the outer JIS chain
deterministic. Tests cover 401/402/403/429, reaching key 7 after six failures,
per-key quarantine, later calls skipping failed keys, annotation dialogue, and
preservation of existing reviews when all seven fail. The installed LiteLLM
Router is also exercised against a local upstream stub without using live keys.

The earlier comparison used three frozen review cases and 21 attempts,
including six reused Flash results. GLM-5.3 low caught all three inserted
fabrications as factual issues; Flash without thinking classified them as
style issues in that case. This is a small application-specific comparison;
Mistral Medium was unavailable for a matched comparison.

GLM-5.3 still mistranslated a university name, and one CL suggestion implied
unverified details about an employer's internal process. Quote checks cannot
prove every suggested rewrite true. The final factual review and application
submission remain human decisions. This change affects the JIS Python review
and annotation-dialogue route, not every Hermes profile's chat model.

Local measurements and deployment records are in
`10_output/_mistral_replacement_eval_20261009/`.
Key fallback validation and deployment records are in
`10_output/_glm53_key_fallback_20261010/`.
