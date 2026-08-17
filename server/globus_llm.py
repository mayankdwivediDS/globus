"""Globus LLM client wrappers — extracted from lead_server.py 2026-06-28
as refactor slice #6v. Provider-dispatch + OpenAI-shape vs Anthropic-
shape glue. Every chat / voice / agent path goes through here to talk
to an LLM.

What's here:
  - GLOBUS_MODEL: default Anthropic model id (used by claude_raw +
    claude paths).
  - globus_call_chat(system, msgs, max_tokens, tools):
        provider dispatcher (cfg('GLOBUS_LLM_PROVIDER')). Defaults to
        claude-oauth via an operator-supplied local proxy; falls back
        to the Anthropic API if that direct-provider key is configured.
  - globus_call_claude_oauth(system, msgs, ...): hits the local
    operator-supplied bridge at 127.0.0.1:8787.
  - globus_call_deepseek_chat(system, msgs, ...): DeepSeek-V3 direct
    (OpenAI-compatible API).
  - globus_call_claude_raw(system, msgs, ...): Anthropic API direct,
    returns the FULL response dict (caller inspects tool_use blocks).
  - globus_call_claude(system, msgs, max_tokens): Anthropic API
    direct with prompt caching on system prompt; returns (text, usage)
    tuple.
  - globus_call_gemini_chat(system, msgs, ...): Gemini API direct
    (generateContent), OpenAI-shape tools/messages in and out.
  - _anthropic_to_openai_shape(resp): glue used by globus_call_chat
    when provider=anthropic.
  - _openai_msgs_to_gemini(messages): glue used by
    globus_call_gemini_chat to convert OpenAI-shape chat history
    (incl. tool_calls / role=tool results) to Gemini's contents shape.

Module deps: cfg (db_helpers), urllib, json, os. No DB writes, no
configure() needed — cfg() reads happen on every call so config
changes take effect immediately without a restart.
"""
from __future__ import annotations
import json
import os
from urllib.request import Request, urlopen
from db_helpers import cfg


GLOBUS_MODEL = "claude-sonnet-4-6"


def globus_call_claude_oauth(system, messages, max_tokens=2000, tools=None,
                              model="sonnet"):
    """Drop-in replacement for globus_call_deepseek_chat that routes to
    an operator-supplied OpenAI-compatible bridge at 127.0.0.1:8787.
    Default model is Sonnet (faster than Opus — matters for voice turn
    latency); override via GLOBUS_OAUTH_MODEL.

    Same signature + return shape as globus_call_deepseek_chat so callers
    are symmetric.

    On failure, raises — the dispatcher may try Anthropic direct."""
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + list(messages),
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = Request(
        "http://127.0.0.1:8787/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def globus_call_chat(system, messages, max_tokens=2000, tools=None,
                      model=None):
    """Dispatcher: picks the LLM provider for Globus chat/voice based on
    config flag GLOBUS_LLM_PROVIDER (DB cfg, env fallback). If the local
    Claude bridge fails, it attempts Anthropic direct; that fallback still
    requires a configured Anthropic API key.

    `model` PINS the model tier for this one call. Leave it None for the
    interactive chat/voice path (which follows GLOBUS_OAUTH_MODEL), but pass
    it explicitly from any BATCH caller — a background job that inherits the
    chat brain's tier silently changes cost and behaviour the moment someone
    retunes chat, and being a batch job, nothing tells you. Cheap, bulk work
    (e.g. classifying a mailbox) should pin a small model; only work that
    genuinely needs judgement should pin a large one.

      claude-oauth (default) → Claude Sonnet via an operator bridge
      deepseek               → DeepSeek-V3 direct (legacy; not used by default)
      anthropic              → Anthropic API (Sonnet) direct
      gemini                 → Gemini API (GEMINI_TEXT_MODEL) direct

    Unrecognized/blank values fall through to the claude-oauth→Anthropic
    default below — set GLOBUS_LLM_PROVIDER explicitly to one of the four
    above, or chat silently never reaches the provider you configured.
    Returns OpenAI-shape dict identical to globus_call_deepseek_chat."""
    provider = (cfg("GLOBUS_LLM_PROVIDER", "claude-oauth")
                or "claude-oauth").strip().lower()
    if provider == "deepseek":
        return globus_call_deepseek_chat(system, messages, max_tokens, tools)
    if provider == "anthropic":
        resp = globus_call_claude_raw(system, messages, max_tokens, tools)
        return _anthropic_to_openai_shape(resp)
    if provider == "gemini":
        return globus_call_gemini_chat(system, messages, max_tokens, tools)
    try:
        return globus_call_claude_oauth(
            system, messages, max_tokens, tools,
            model=(model or cfg("GLOBUS_OAUTH_MODEL", "sonnet")))
    except Exception as e:
        # Stay on Claude: fall back to the Anthropic API direct (Sonnet),
        # not DeepSeek, so the Globus brain is always Claude.
        print(f"[globus-chat] OAuth proxy failed ({type(e).__name__}); "
              "falling back to Anthropic API direct (Claude)", flush=True)
        resp = globus_call_claude_raw(system, messages, max_tokens, tools)
        return _anthropic_to_openai_shape(resp)


def _anthropic_to_openai_shape(claude_resp):
    """Convert Anthropic-shape response to OpenAI-shape so callers built
    around globus_call_deepseek_chat keep working unchanged."""
    content_blocks = claude_resp.get("content") or []
    text = "".join(b.get("text", "") for b in content_blocks
                   if b.get("type") == "text")
    tool_calls = []
    for b in content_blocks:
        if b.get("type") == "tool_use":
            tool_calls.append({
                "id": b.get("id"),
                "type": "function",
                "function": {
                    "name": b.get("name"),
                    "arguments": json.dumps(b.get("input") or {}),
                }})
    msg = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "id": claude_resp.get("id"),
        "choices": [{"index": 0, "message": msg,
                     "finish_reason": "stop"}],
        "model": claude_resp.get("model"),
        "usage": claude_resp.get("usage", {}),
    }


def globus_call_deepseek_chat(system, messages, max_tokens=2000, tools=None):
    """OpenAI-compatible DeepSeek chat completion with optional tools.
    Returns the full response dict (so caller can inspect tool_calls).
    System message is the first item in `messages`; we prepend it here
    so callers stay symmetric with the old globus_call_claude(system, msgs)
    signature."""
    api_key = (cfg("DEEPSEEK_API_KEY")
               or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not configured")
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system}] + list(messages),
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })
    with urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def globus_call_claude_raw(system, messages, max_tokens=1500, tools=None):
    """Same as globus_call_claude but returns the FULL Anthropic response
    dict (so callers can inspect tool_use blocks). Used by the tool-use
    loop in globus_chat_send."""
    key = cfg("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    system_blocks = [{
        "type": "text",
        "text": system,
        "cache_control": {"type": "ephemeral"},
    }]
    body_dict = {
        "model": GLOBUS_MODEL,
        "max_tokens": max_tokens,
        "system": system_blocks,
        "messages": messages,
    }
    if tools:
        body_dict["tools"] = tools
    body = json.dumps(body_dict).encode()
    req = Request("https://api.anthropic.com/v1/messages",
                  data=body, method="POST",
                  headers={"x-api-key": key,
                           "anthropic-version": "2023-06-01",
                           "anthropic-beta": "prompt-caching-2024-07-31",
                           "content-type": "application/json"})
    with urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def globus_call_claude(system, messages, max_tokens=1500):
    """Anthropic Messages call with PROMPT CACHING on the system prompt.
    The persona+digest portion is identical across calls — caching it
    drops input costs 50-90% (Anthropic charges ~10% for cache hits and
    1.25x once for cache creation, valid for 5 min between calls).
    System prompt < 1024 tokens won't be cached (Anthropic minimum)."""
    key = cfg("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    system_blocks = [{
        "type": "text",
        "text": system,
        "cache_control": {"type": "ephemeral"},
    }]
    body = json.dumps({
        "model": GLOBUS_MODEL,
        "max_tokens": max_tokens,
        "system": system_blocks,
        "messages": messages,
    }).encode()
    req = Request("https://api.anthropic.com/v1/messages",
                  data=body, method="POST",
                  headers={"x-api-key": key,
                           "anthropic-version": "2023-06-01",
                           "anthropic-beta": "prompt-caching-2024-07-31",
                           "content-type": "application/json"})
    with urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode())
    parts = d.get("content") or []
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
    usage = d.get("usage") or {}
    return text, usage


GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
GEMINI_EMBED_MODEL = "gemini-embedding-001"
GEMINI_EMBED_DIM = 768
GEMINI_EMBED_BATCH = 100


def _openai_tools_to_gemini(tools):
    """OpenAI tool defs ({"type":"function","function":{name,description,
    parameters}}) -> Gemini's [{"functionDeclarations": [...]}] shape."""
    if not tools:
        return None
    decls = []
    for t in tools:
        fn = t.get("function") or t
        decls.append({
            "name": fn.get("name"),
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return [{"functionDeclarations": decls}]


def _openai_msgs_to_gemini(messages):
    """OpenAI-shape chat history -> Gemini `contents` list.

    Tracks tool_call_id -> function name (Gemini function responses are
    matched by name, not id) so role=tool results can be converted back
    into functionResponse parts. Consecutive tool messages are merged
    into a single Gemini content, matching how Gemini expects the
    responses for one multi-call assistant turn to arrive together."""
    contents = []
    call_id_to_name = {}
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        if role == "user":
            contents.append({"role": "user",
                              "parts": [{"text": m.get("content") or ""}]})
        elif role == "assistant":
            parts = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                call_id_to_name[tc.get("id")] = name
                args_raw = fn.get("arguments") or "{}"
                try:
                    args = (json.loads(args_raw) if isinstance(args_raw, str)
                            else (args_raw or {}))
                except json.JSONDecodeError:
                    args = {}
                parts.append({"functionCall": {"name": name, "args": args}})
            contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            name = call_id_to_name.get(m.get("tool_call_id"), "")
            raw = m.get("content") or "{}"
            try:
                response = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                response = {"result": raw}
            if not isinstance(response, dict):
                response = {"result": response}
            part = {"functionResponse": {"name": name, "response": response}}
            if contents and contents[-1]["role"] == "function":
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "function", "parts": [part]})
    return contents


def globus_call_gemini_chat(system, messages, max_tokens=2000, tools=None,
                             model=None):
    """Gemini API direct (generateContent). Same OpenAI-shape in/out as
    globus_call_deepseek_chat so callers stay symmetric across providers."""
    api_key = (cfg("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")
    model = (model or cfg("GEMINI_TEXT_MODEL", GEMINI_DEFAULT_MODEL)
              or GEMINI_DEFAULT_MODEL).strip()
    body = {
        "contents": _openai_msgs_to_gemini(messages),
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.4,
            # 2.5-series models "think" by default, spending maxOutputTokens
            # on invisible reasoning before any visible text — with a small
            # budget that can consume the whole call and return empty text
            # (finishReason=MAX_TOKENS, 0 visible chars). Off by default here
            # to match the other providers' turn latency/cost in this loop.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    gemini_tools = _openai_tools_to_gemini(tools)
    if gemini_tools:
        body["tools"] = gemini_tools
    req = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    candidates = d.get("candidates") or []
    cand_parts = (candidates[0].get("content") or {}).get("parts") or [] if candidates else []
    text = "".join(p.get("text", "") for p in cand_parts if "text" in p)
    tool_calls = []
    for i, p in enumerate(cand_parts):
        fc = p.get("functionCall")
        if fc:
            tool_calls.append({
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": fc.get("name"),
                    "arguments": json.dumps(fc.get("args") or {}),
                }})
    msg = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    um = d.get("usageMetadata") or {}
    return {
        "id": None,
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
        "model": model,
        "usage": {
            "prompt_tokens": um.get("promptTokenCount", 0),
            "completion_tokens": um.get("candidatesTokenCount", 0),
            "total_tokens": um.get("totalTokenCount", 0),
        },
    }


def globus_call_gemini_embed(texts, model=None, dim=GEMINI_EMBED_DIM):
    """Embed a list of strings via Gemini's batchEmbedContents. Returns a
    list of float-vectors, same order/length as `texts`. Chunks internally
    at GEMINI_EMBED_BATCH per request (not officially documented as batch-
    capable, but confirmed working — see drive_index.py's one caller).
    Used by the FAISS metadata index, never by the interactive chat loop
    (embedding is a batch/offline concern, not a per-turn one)."""
    api_key = (cfg("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")
    model = (model or GEMINI_EMBED_MODEL).strip()
    out = []
    for i in range(0, len(texts), GEMINI_EMBED_BATCH):
        chunk = texts[i:i + GEMINI_EMBED_BATCH]
        body = {"requests": [
            {"model": f"models/{model}",
             "content": {"parts": [{"text": t}]},
             "outputDimensionality": dim}
            for t in chunk]}
        req = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents?key={api_key}",
            data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode("utf-8"))
        out.extend(e.get("values") or [] for e in (d.get("embeddings") or []))
    return out
