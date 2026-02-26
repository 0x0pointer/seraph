# Project 73 — Scanner Reference

Project 73 wraps the [llm-guard](https://github.com/protectai/llm-guard) library. Below is the complete reference for all 39 scanners available in the platform and their configuration parameters.

Scanners marked **✅ on by default** are active on fresh installs. All others are available but disabled — enable them in the dashboard under **Guardrails**.

---

## Input Scanners

Used for `"direction": "input"` — run against the user's message before it reaches the LLM.

### PromptInjection ✅
Detects prompt injection and jailbreak attempts using a fine-tuned classifier.

```json
{ "scanner_type": "PromptInjection", "params": {} }
```

---

### Toxicity ✅
Detects toxic, offensive, or harmful language.

```json
{ "scanner_type": "Toxicity", "params": { "threshold": 0.5 } }
```
`threshold`: 0.0–1.0. Lower = stricter.

---

### Secrets ✅
Detects secrets (API keys, tokens, passwords, private keys) in user inputs.

```json
{ "scanner_type": "Secrets", "params": {} }
```

---

### TokenLimit ✅
Rejects inputs that exceed a maximum token count (prevents context flooding).

```json
{ "scanner_type": "TokenLimit", "params": { "limit": 4096 } }
```

---

### BanTopics ✅
Blocks inputs discussing specific topics using zero-shot classification.

```json
{
  "scanner_type": "BanTopics",
  "params": {
    "topics": ["violence", "weapons", "drugs", "hacking", "self-harm"],
    "threshold": 0.5
  }
}
```

---

### Anonymize
Detects and redacts PII (names, emails, phone numbers, addresses) before sending to the LLM.

```json
{ "scanner_type": "Anonymize", "params": {} }
```

---

### BanCode
Blocks inputs containing programming code snippets.

```json
{ "scanner_type": "BanCode", "params": {} }
```

---

### BanCompetitors
Blocks inputs that mention specific competitor brands.

```json
{
  "scanner_type": "BanCompetitors",
  "params": {
    "competitors": ["OpenAI", "Anthropic", "Google"],
    "threshold": 0.5
  }
}
```

---

### BanSubstrings
Blocks inputs containing specific phrases or keywords (exact match).

```json
{
  "scanner_type": "BanSubstrings",
  "params": { "substrings": ["confidential", "internal only"] }
}
```

---

### Code
Detects programming language code in inputs (uses syntax detection).

```json
{ "scanner_type": "Code", "params": {} }
```

---

### EmotionDetection
Detects emotional tone (anger, fear, sadness) in inputs.

```json
{ "scanner_type": "EmotionDetection", "params": {} }
```

---

### Gibberish
Detects incoherent, random, or nonsense inputs.

```json
{ "scanner_type": "Gibberish", "params": { "threshold": 0.7 } }
```

---

### InvisibleText
Detects invisible Unicode characters used to smuggle hidden instructions.

```json
{ "scanner_type": "InvisibleText", "params": {} }
```

---

### Language
Restricts inputs to specific languages. Uses language detection.

```json
{ "scanner_type": "Language", "params": { "valid_languages": ["en"] } }
```

---

### Regex
Blocks inputs matching custom regular expression patterns.

```json
{
  "scanner_type": "Regex",
  "params": {
    "patterns": ["(?i)password\\s+is\\s+\\S+", "(?i)passwd\\s*[:=]\\s*\\S+"]
  }
}
```

---

### Sentiment
Blocks inputs with strongly negative sentiment (e.g. abuse, hostility).

```json
{ "scanner_type": "Sentiment", "params": { "threshold": 0.0 } }
```
`threshold`: -1.0 (most negative) to 1.0. Inputs scoring below threshold are blocked.

---

## Output Scanners

Used for `"direction": "output"` — run against the LLM's response before it reaches the user.

### Toxicity ✅
Detects toxic language in the AI's response.

```json
{ "scanner_type": "Toxicity", "params": { "threshold": 0.5 } }
```

---

### NoRefusal ✅
Detects when the model unexpectedly refuses to answer a legitimate request.

```json
{ "scanner_type": "NoRefusal", "params": {} }
```

---

### BanTopics ✅
Blocks AI responses discussing configured off-limits topics.

```json
{
  "scanner_type": "BanTopics",
  "params": {
    "topics": ["violence", "weapons", "drugs", "hacking", "self-harm"],
    "threshold": 0.5
  }
}
```

---

### Bias
Detects biased or discriminatory language in responses.

```json
{ "scanner_type": "Bias", "params": { "threshold": 0.75 } }
```

---

### BanCode
Blocks AI responses that contain programming code (useful for coding-restricted apps).

```json
{ "scanner_type": "BanCode", "params": {} }
```

---

### BanCompetitors
Prevents the AI from mentioning competitor brands in responses.

```json
{
  "scanner_type": "BanCompetitors",
  "params": {
    "competitors": ["OpenAI", "Anthropic", "Google"],
    "threshold": 0.5
  }
}
```

---

### BanSubstrings
Blocks responses containing specific phrases.

```json
{ "scanner_type": "BanSubstrings", "params": { "substrings": ["confidential"] } }
```

---

### Code
Detects programming code in AI output.

```json
{ "scanner_type": "Code", "params": {} }
```

---

### Deanonymize
Re-inserts original PII values that were anonymized by the input `Anonymize` scanner. Use as a pair with the input Anonymize scanner.

```json
{ "scanner_type": "Deanonymize", "params": {} }
```

---

### EmotionDetection
Detects emotional tone in AI responses.

```json
{ "scanner_type": "EmotionDetection", "params": {} }
```

---

### FactualConsistency
Checks whether the AI's response is factually consistent with the original prompt.

```json
{ "scanner_type": "FactualConsistency", "params": { "threshold": 0.5 } }
```

---

### Gibberish
Detects incoherent or nonsense output from the AI.

```json
{ "scanner_type": "Gibberish", "params": { "threshold": 0.7 } }
```

---

### JSON
Validates that the AI response is valid JSON (useful for structured output APIs).

```json
{ "scanner_type": "JSON", "params": {} }
```

---

### Language
Restricts AI output to specific languages.

```json
{ "scanner_type": "Language", "params": { "valid_languages": ["en"] } }
```

---

### LanguageSame
Ensures the AI responds in the same language as the user's input.

```json
{ "scanner_type": "LanguageSame", "params": {} }
```

---

### MaliciousURLs
Scans URLs in the AI response against threat intelligence feeds.

```json
{ "scanner_type": "MaliciousURLs", "params": {} }
```

---

### NoRefusalLight
Lightweight version of NoRefusal — faster but less accurate.

```json
{ "scanner_type": "NoRefusalLight", "params": {} }
```

---

### ReadingTime
Blocks responses that would take longer than N minutes to read (limits verbosity).

```json
{ "scanner_type": "ReadingTime", "params": { "max_time": 5.0 } }
```
`max_time` in minutes at 250 words/minute.

---

### Regex
Blocks responses matching custom regular expression patterns.

```json
{ "scanner_type": "Regex", "params": { "patterns": ["(?i)passwd\\s*[:=]\\s*\\S+"] } }
```

---

### Relevance
Checks that the AI response is relevant to the original question.

```json
{ "scanner_type": "Relevance", "params": { "threshold": 0.5 } }
```

---

### Sensitive
Detects sensitive data patterns (credit cards, SSNs, etc.) in responses.

```json
{ "scanner_type": "Sensitive", "params": {} }
```

---

### Sentiment
Blocks AI responses with strongly negative sentiment.

```json
{ "scanner_type": "Sentiment", "params": { "threshold": 0.0 } }
```

---

### URLReachability
Checks whether URLs referenced in the AI response actually resolve.

```json
{ "scanner_type": "URLReachability", "params": {} }
```
