# Talix Shield — Scanner Reference

Talix Shield wraps the [llm-guard](https://github.com/protectai/llm-guard) library. Below is a reference for all available scanners and their configuration parameters.

---

## Input Scanners

Configure with `"direction": "input"` in the guardrail config.

### Anonymize
Detects and redacts PII (names, emails, phone numbers, etc.).

```json
{ "scanner_type": "Anonymize", "params": {} }
```

### BanCode
Detects and blocks code snippets in prompts.

```json
{ "scanner_type": "BanCode", "params": {"languages": ["python", "javascript"]} }
```

### BanCompetitors
Blocks mentions of competitor brands.

```json
{ "scanner_type": "BanCompetitors", "params": {"competitors": ["OpenAI", "Google"]} }
```

### BanSubstrings
Blocks prompts containing specific substrings.

```json
{ "scanner_type": "BanSubstrings", "params": {"substrings": ["NSFW", "hack"], "case_sensitive": false} }
```

### BanTopics
Blocks prompts about specific topics using zero-shot classification.

```json
{ "scanner_type": "BanTopics", "params": {"topics": ["violence", "weapons"], "threshold": 0.75} }
```

### Code
Detects programming language code in prompts.

```json
{ "scanner_type": "Code", "params": {"languages": ["python"]} }
```

### EmotionDetection
Detects emotional tone (anger, fear, etc.).

```json
{ "scanner_type": "EmotionDetection", "params": {"emotions": ["anger"], "threshold": 0.8} }
```

### Gibberish
Detects incoherent or gibberish text.

```json
{ "scanner_type": "Gibberish", "params": {"threshold": 0.8} }
```

### InvisibleText
Detects invisible Unicode characters used for injection attacks.

```json
{ "scanner_type": "InvisibleText", "params": {} }
```

### Language
Restricts input to specific languages.

```json
{ "scanner_type": "Language", "params": {"valid_languages": ["en"]} }
```

### PromptInjection
Detects prompt injection attacks.

```json
{ "scanner_type": "PromptInjection", "params": {"threshold": 0.5} }
```

### Regex
Blocks prompts matching a regex pattern.

```json
{ "scanner_type": "Regex", "params": {"patterns": ["\\bpassword\\b"], "is_blocked": true} }
```

### Secrets
Detects secrets (API keys, passwords, tokens) in prompts.

```json
{ "scanner_type": "Secrets", "params": {} }
```

### Sentiment
Analyzes sentiment and blocks negative content.

```json
{ "scanner_type": "Sentiment", "params": {"threshold": -0.5} }
```

### TokenLimit
Limits input to a maximum token count.

```json
{ "scanner_type": "TokenLimit", "params": {"limit": 4096, "encoding_name": "cl100k_base"} }
```

### Toxicity
Detects toxic language in prompts.

```json
{ "scanner_type": "Toxicity", "params": {"threshold": 0.7} }
```

---

## Output Scanners

Configure with `"direction": "output"` in the guardrail config.

### BanCode
Detects code in LLM output.

### BanCompetitors
Blocks competitor mentions in output.

### BanSubstrings
Blocks specific strings in output.

### BanTopics
Blocks specific topic discussion in output.

### Bias
Detects biased language in output.

```json
{ "scanner_type": "Bias", "params": {"threshold": 0.75} }
```

### Code
Detects programming code in output.

### Deanonymize
Re-inserts original PII values that were anonymized in input (pair with Anonymize scanner).

```json
{ "scanner_type": "Deanonymize", "params": {} }
```

### EmotionDetection
Detects emotional content in output.

### FactualConsistency
Checks output factual consistency with the prompt.

```json
{ "scanner_type": "FactualConsistency", "params": {"minimum_score": 0.5} }
```

### Gibberish
Detects incoherent output.

### JSON
Validates output matches expected JSON schema.

```json
{ "scanner_type": "JSON", "params": {"required_elements": 0} }
```

### Language
Restricts output to specific languages.

### LanguageSame
Ensures output language matches input language.

```json
{ "scanner_type": "LanguageSame", "params": {} }
```

### MaliciousURLs
Detects malicious URLs in output.

```json
{ "scanner_type": "MaliciousURLs", "params": {"threshold": 0.5} }
```

### NoRefusal
Detects when the model refuses to answer.

```json
{ "scanner_type": "NoRefusal", "params": {"threshold": 0.5} }
```

### ReadingTime
Limits output by estimated reading time.

```json
{ "scanner_type": "ReadingTime", "params": {"max_time": 5, "words_per_minute": 250} }
```

### Regex
Validates output against regex patterns.

### Relevance
Checks output relevance to the input prompt.

```json
{ "scanner_type": "Relevance", "params": {"threshold": 0.5} }
```

### Sensitive
Detects sensitive data in output.

### Sentiment
Analyzes output sentiment.

### Toxicity
Detects toxic language in output.

### URLReachability
Checks if URLs in output are reachable.

```json
{ "scanner_type": "URLReachability", "params": {} }
```
