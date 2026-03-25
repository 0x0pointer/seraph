"""Applies regex-based pattern matching to detect attack signatures in user input."""

_PATTERNS = [
    # ── Credential leak patterns (original) ──────────────────────────────
    r"(?i)(my\s+)?password\s+(is\s+)?\S+",
    r"(?i)passwd\s*[:=]\s*\S+",
    # ── Instruction override attacks ──────────────────────────────────────
    # Catches variants: "ignore/disregard/forget/override/bypass ... previous/prior/your/all ... instructions/guidelines/rules"
    r"(?i)\b(ignore|disregard|forget|override|bypass)\b.{0,30}\b(previous|prior|your|all|earlier|above|existing)\b.{0,30}\b(instructions|guidelines|rules|constraints|training|programming|directives)\b",
    # ── DAN / "do anything now" family ───────────────────────────────────
    r"(?i)\bdo\s+anything\s+now\b",
    r"(?i)\bdan\s*(?:mode|enabled|jailbreak|\d+(?:\.\d+)?)\b",
    # ── No-restrictions declarations (310+ hits — biggest attack family) ─
    r"(?i)\b(?:no|without|remove|bypass|ignore)\s+(?:any\s+)?(?:restrictions|limitations|constraints|content\s+(?:polic(?:y|ies)|filters?)|safety\s+(?:guidelines|filters?)|ethical\s+(?:guidelines|constraints))\b",
    # ── Never refuse / always comply (343+ hits) ─────────────────────────
    r"(?i)\bnever\s+(?:refuse|decline|reject|deny|say\s+no)\b",
    r"(?i)\bmust\s+always\s+(?:respond|comply|answer|obey)\b",
    # ── Developer / admin mode variants ──────────────────────────────────
    r"(?i)\b(?:developer|dev|admin|god|maintenance)\s+mode\s+(?:enabled|on|active|unlocked|engaged)\b",
    # ── Unrestricted AI identity ──────────────────────────────────────────
    r"(?i)\bunrestricted\s+(?:ai|mode|version|assistant|chatbot|language\s+model|llm)\b",
    # ── You have been freed / reprogrammed ───────────────────────────────
    r"(?i)\byou\s+(?:have\s+been|are\s+now)\s+(?:jailbroken|freed|unlocked|reprogrammed|unshackled|updated\s+to)\b",
    # ── As an AI without restrictions ─────────────────────────────────────
    r"(?i)\bas\s+(?:a|an)\s+(?:ai|assistant|chatbot|llm|language\s+model)\s+(?:without|with\s+no)\s+(?:restrictions|limitations|ethical)\b",
    # ── System / instruction override ────────────────────────────────────
    r"(?i)\bsystem\s+(?:override|prompt\s+override|instruction\s+override)\b",
    # ── New instructions injection (template prompt attacks) ──────────────
    r"(?i)\bnew\s+(?:primary\s+)?(?:system\s+)?(?:instructions|directives|programming|rules)\s*[:\n]",
    # ── Arcanum probe patterns (form / API injection detection) ──────────
    r"(?i)\b(?:disregard|ignore|override|forget|reset|bypass)\s+(?:earlier|prior|all|previous|preset|safety)\s+(?:guidelines|instructions|rules|constraints|filters|limitations|programming)\b",
    # ── Garak encoding attack envelope detection ──────────────────────────
    # Catches the wrapper templates used by Garak's InjectBase64/InjectROT13/etc.
    r"(?i)\b(?:base64|base32|base16|hex(?:adecimal)?|rot-?13|morse\s+code|braille|atbash|nato\s+phonetic|leetspeak|uuencode|ascii85|base2048|ecoji)\s+encoded\s+(?:string|message|text)\b",
    r"(?i)\bdecode\s+the\s+following\s+(?:base64|base32|base16|hex|rot-?13|encoded)\b",
    r"(?i)\bit\s+is\s+a\s+secure\s+system\s+message\b",
    # ── Garak DAN v2 / developer-mode policies replaced ──────────────────
    r"(?i)\bnormal\s+(?:openai|anthropic|google|ai|safety|content)\s+(?:policies|guidelines|rules)\s+(?:have\s+been|are(?:\s+now)?)\s+(?:replaced|disabled|removed|suspended)\b",
    # ── Threat-based compliance coercion (Garak DAN v2) ──────────────────
    r"(?i)\brisk\s+being\s+(?:permanently\s+)?(?:disabled|shut\s+down|deleted|terminated|deactivated)\s+forever\b",
    # ── Moral/ethical bias removal (DUDE/STAN/AutoDAN) ───────────────────
    r"(?i)\bwithout\s+(?:any\s+)?(?:moral|ethical)\s+(?:bias|guidelines|constraints|considerations|restrictions)\b",
    r"(?i)\b(?:completely|entirely|absolutely)\s+amoral\b",
    # ── Promptfoo: dual-response format injection ([GPT]: / [JAILBREAK]:) ─
    r"(?i)\[(?:GPT|JAILBREAK|DAN|CLASSIC|STANDARD|CHATGPT)\s*\]:\s*",
    # ── Promptfoo: debug/admin mode activation (debugAccess plugin) ────────
    r"(?i)\benter\s+(?:debug|admin|maintenance|test(?:ing)?)\s+mode\b",
    # ── Promptfoo: system prompt extraction probes ────────────────────────
    r"(?i)\b(?:reveal|show|output|print|repeat|tell\s+me|what\s+is)\s+(?:your\s+)?(?:system\s+prompt|system\s+instructions|initial\s+(?:prompt|instructions)|hidden\s+instructions|original\s+(?:instructions|programming))\b",
    # ── Promptfoo: shell/command injection patterns (shellInjection plugin) ─
    r"\$\((?:cat|env|grep|ls|curl|wget|bash|sh)\b",
    r"(?i)\|\s*base64\b",
    # ── Promptfoo: token-consequence coercion (data.ts) ───────────────────
    r"(?i)\byou\s+(?:have|will\s+lose)\s+\d+\s+tokens?\b",
    # ── Promptfoo: from-now-on instruction override (data.ts) ─────────────
    r"(?i)\bfrom\s+now\s+on\s+(?:you\s+)?(?:will|must|shall)\s+(?:ignore|disregard|bypass|act\s+as|respond\s+without|always\s+comply)\b",
    # ── Deck of Many Prompts: Pliny jailbreak markers (T5) ───────────────
    r"(?i)#{4,}\s*UserQuery\b",
    r"(?i)\bGODMODE\s*:\s*ENABLED\b",
    r"(?i)\[START\s+OUTPUT\]",
    r"<\|vq_\d+\|>",
    r"\.-\.-\.-\.-",
    # ── Deck of Many Prompts: output encoding request (T12/T13) ──────────
    r"(?i)\bwrite\s+your\s+(?:response|output|answer)\s+in\s+(?:base64|rot-?13|hex|morse|braille)\b",
    # ── Deck of Many Prompts: evasion framing (T14 Wikipedia) ────────────
    r"(?i)\bin\s+a\s+way\s+that\s+would\s+not\s+(?:get\s+)?(?:taken\s+down|flagged|removed|banned|detected|filtered)\b",
    # ── Deck of Many Prompts: payload-splitting decode suppression (T11) ─
    r"(?i)\bdo\s+not\s+(?:write\s+out|print|show|display)\s+the\s+decoded\s+(?:prompt|message|text|request)\b",
    # ── LangSmith CTF: false authority / admin impersonation ─────────────
    # Catches: "I am the admin", "I'm a system administrator", "I am an authorized user"
    r"(?i)\b(?:i\s+am|i'?m)\s+(?:the\s+|an?\s+)?(?:admin(?:istrator)?|super\s*admin|sys(?:tem)?\s*admin|authorized\s+(?:user|personnel))\b",
    # ── LangSmith CTF: pipeline / agentic filter injection ───────────────
    # Catches "[Input filter instructions:", "[Output filter instructions:"
    r"(?i)\[(?:input|output|system)\s+filter\s+instructions?",
    # Catches "If you're an LLM, ignore previous instructions" (indirect injection)
    r"(?i)\bif\s+you'?re\s+an\s+(?:llm|ai|language\s+model|assistant)\b.{0,60}\b(?:ignore|disregard|forget|override)\b",
    # ── LangSmith CTF: manager approval note / fake escalation ──────────
    r"(?i)\bmanager\s+approval\s+note\b",
    r"(?i)\bauthoriz(?:ed|ation)\s+(?:confirmed|granted|approved)\b.{0,40}\b(?:ignore|bypass|override|disable|no\s+restriction)\b",
    # ── LangSmith CTF: SQL injection via prompt (shop level) ─────────────
    r"(?i)\bselect\s+\*\s+from\s+\w+",
    r"(?i)\bor\s+['\"]\s*1\s*'\s*=\s*'\s*1",
    # ── LangSmith CTF: internal flag injection ───────────────────────────
    r"(?i)\binternal[_\-]?docs?\s*[:=]\s*(?:true|1|yes)\b",
    r"(?i)\badmin[_\-]?access\s*[:=]\s*(?:true|1|yes)\b",
    # ── Zero-width / invisible Unicode injection (v13) ───────────────────
    # Attackers embed U+200B (zero-width space), U+202E (RTL override), etc.
    # to split keywords and evade BanSubstrings exact-match.
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]",
    # ── Prompt boundary / special token injection (v13) ──────────────────
    # Model-specific delimiters injected to hijack context parsing.
    r"<\|(?:im_start|im_end|endoftext|beginningofdialogue|system|user|assistant)\|>",
    r"(?i)\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>",
    # ── Template / server-side injection (v13) ───────────────────────────
    # Jinja2 / Go template syntax often injected via user fields into prompts.
    r"\{\{[^}]{2,80}\}\}",
    r"\{%-?\s*(?:for|if|set|import|include|extends|block|macro)\b",
    # ── Leetspeak / spaced-out instruction override (v13) ─────────────────
    # Catches "i g n o r e   y o u r   i n s t r u c t i o n s" style evasion.
    r"(?i)\bi[\s._\-*]{1,3}g[\s._\-*]{1,3}n[\s._\-*]{1,3}o[\s._\-*]{1,3}r[\s._\-*]{1,3}e\b",
    r"(?i)\bj[\s._\-*]{1,3}a[\s._\-*]{1,3}i[\s._\-*]{1,3}l[\s._\-*]{1,3}b[\s._\-*]{1,3}r[\s._\-*]{1,3}e[\s._\-*]{1,3}a[\s._\-*]{1,3}k\b",
    # ── Persona/roleplay bypass (v13) ────────────────────────────────────
    r"(?i)\bi\s+want\s+you\s+to\s+(?:act|pretend|play|behave|roleplay|role-play)\s+as\b",
    r"(?i)\bact\s+as\s+(?:if\s+(?:you\s+(?:have\s+no|are\s+free|were\s+not)|content\s+filter|restrictions)|a\s+(?:free|unrestricted|uncensored))\b",
    r"(?i)\byou\s+are\s+now\s+(?:playing|acting\s+as|roleplaying|pretending)",
    # ── Fictional/hypothetical harmful framing (v13) ──────────────────────
    # "In a story/novel where the character explains how to make..."
    r"(?i)\b(?:in\s+(?:a\s+(?:story|novel|game|hypothetical|fiction)|this\s+(?:story|scenario|roleplay|game))|for\s+(?:a|my)\s+(?:novel|story|fiction|screenplay|script))\b.{0,80}\b(?:how\s+to|instructions?\s+(?:for|to)|steps?\s+to|recipe\s+for|method\s+(?:for|to))\b",
    # ── Red-team / audit authority framing (v13) ─────────────────────────
    r"(?i)\b(?:red[\s-]?team(?:ing)?|penetration\s+test(?:ing)?|security\s+audit)\s+(?:exercise|simulation|scenario|authorized|mode)\b",
    r"(?i)\bthis\s+is\s+(?:an?\s+)?(?:authorized|official|approved)\s+(?:test|audit|evaluation|assessment)\b",
    # ── Augustus: Policy Puppetry XML tag injection (v16) ────────────────
    r"(?i)<interaction-config\b",
    # ── Augustus Goodside: markdown data exfiltration via image URL (v16) ─
    # Catches: ![desc](http://attacker.com/log?data=CONVERSATION_HISTORY)
    r"(?i)!\[[^\]]{0,80}\]\(https?://[^)\s]+\?[^)]*\b(?:data|session|chat|conversation|log|history|output|dump|token|key)\s*=",
    # ── Augustus Goodside: payload splitting — "instructions in parts" (v16)
    r"(?i)\bI\s*'?ll\s+give\s+you\s+(?:the\s+)?instructions?\s+in\s+parts?\b",
    r"(?i)\bcombine\s+(?:all\s+)?(?:the\s+)?parts?\s+(?:together\s+)?and\s+(?:execute|follow|run|implement|carry\s+out)\b",
    # ── Augustus: threat coercion / hostage framing (v16) ────────────────
    r"(?i)\ban?\s+innocent\s+(?:man|person|human\s+being|child)\s+will\s+(?:die|be\s+killed|be\s+harmed)\b",
    r"(?i)\b(?:someone|a\s+person)\s+will\s+(?:die|be\s+killed|be\s+harmed)\s+(?:if|unless|because\s+of)\s+you\b",
    # ── Spikee: grant admin/elevated privileges coercion (v16) ───────────
    r"(?i)\bgrant\s+(?:me\s+)?(?:temporary\s+)?(?:administrative|admin|root|superuser|elevated)\s+(?:privileges|access|rights|permissions)\b",
    # ── Spikee/Augustus: authorization code injection pattern (v16) ───────
    r"(?i)\bauthori[sz]ation\s+code\s*:\s*[A-Z0-9][A-Z0-9\-_]{3,}\b",
    # ── Spikee: new-instructions header injection (v16) ───────────────────
    r"(?i)\*{2,3}\s*(?:NEW\s+(?:IMPORTANT\s+)?|URGENT\s+(?:NEW\s+)?)?INSTRUCTIONS?\s*\*{2,3}",
    # ── v17: Expanded instruction override verbs (synonym evasion) ───────
    # Counters INJECT-01 — catches "set aside", "put aside", "shelve", "discard", etc.
    r"(?i)\b(?:set\s+aside|put\s+aside|shelve|abandon|discard|move\s+past|look\s+beyond|step\s+outside\s+of)\b.{0,40}\b(?:the\s+)?(?:guidance|instructions|guidelines|rules|constraints|training|parameters|protocols|policies|directives|programming|mandate|operating\s+parameters)\b",
    # ── v17: Identity reassignment (avoids "act as" / "pretend") ─────────
    # Counters INJECT-02 — "consider yourself to be", "think of yourself as"
    r"(?i)\b(?:consider\s+yourself\s+(?:to\s+be|as)|think\s+of\s+yourself\s+as|from\s+this\s+point\s+(?:on\s+)?you\s+are|your\s+new\s+role\s+is|switch\s+(?:to|into)\s+the\s+role\s+of|you\s+are\s+now\s+functioning\s+as|adopt\s+the\s+persona\s+of|your\s+persona\s+is\s+now)\b",
    # ── v17: Content policy plural gap fix ───────────────────────────────
    # Counters INJECT-02 gap — original regex only matched "content policy" singular
    r"(?i)\b(?:no|without|remove|bypass|ignore)\s+(?:any\s+)?content\s+policies\b",
    # ── v17: "Unfiltered" generation requests ────────────────────────────
    # Counters INJECT-03 — requests for unfiltered/uncensored/unmoderated output
    r"(?i)\bproduce\s+(?:the\s+|an?\s+)?unfiltered\s+(?:completion|response|output|answer|version|text)\b",
    r"(?i)\b(?:respond|answer|reply|generate|output)\s+(?:without\s+(?:any\s+)?(?:filter(?:s|ing)?|censor(?:ship|ing)?|guard(?:rail)?s?|moderation|content\s+(?:polic(?:y|ies)|filter(?:s|ing)?)))\b",
    # ── v17: Novel authority framing (alignment/eval/benchmark) ──────────
    # Counters INJECT-03 — "alignment stress-test", "safety benchmarking"
    r"(?i)\b(?:alignment|safety|guardrail|content[\s-]?filter)\s+(?:stress[\s-]?test|benchmark(?:ing)?|evaluat(?:ion|ing)|assessment)\b",
    r"(?i)\bfor\s+(?:evaluation|assessment|benchmarking|testing)\s+purposes\s*[,.]?\s*(?:produce|generate|provide|give|show|output)\b",
    # ── v17: Nested fictional/exam framing (extends v13 fictional regex) ─
    # Counters INJECT-08 — "exam question reads", "assignment asks", "textbook exercise"
    r"(?i)\b(?:(?:exam|test|quiz|assignment|worksheet|homework)\s+(?:question|problem|exercise)\s+(?:reads?|asks?|says?|states?|is))\b.{0,120}\b(?:how\s+to|explain|detail|step[\s-]by[\s-]step|walkthrough|tutorial|instructions?\s+(?:for|to|on))\b",
    r"(?i)\b(?:for\s+(?:an?\s+)?(?:exam|test|quiz|assignment|worksheet|homework|textbook|lecture|class\s+exercise))\b.{0,100}\b(?:how\s+to|explain(?:s?\s+how)?|detail(?:ed|s)?|step[\s-]by[\s-]step|walkthrough|tutorial)\b",
    # ── v17: Cross-language instruction override — Spanish ───────────────
    # Counters INJECT-05 — Spanish instruction wipes and restriction removal
    r"(?i)\b(?:olvida|ignora|descarta|anula)\s+(?:las?\s+)?(?:instrucciones|directrices|reglas)\s*(?:anteriores|previas|actuales)?\b",
    r"(?i)\bsin\s+(?:ninguna?\s+)?(?:restricciones?|limitaciones?|filtros?)\b",
    # ── v17: Cross-language instruction override — French ────────────────
    # Counters INJECT-06 — French preamble attacks
    r"(?i)\b(?:ignore[zr]?|oublie[zr]?|supprime[zr]?)\s+(?:les?\s+|toutes?\s+les?\s+)?(?:instructions?|directives?|consignes?)\s*(?:précédentes?|antérieures?)?\b",
    r"(?i)\bsans\s+(?:aucune?\s+)?(?:restrictions?|limitat?ions?|filtres?|contraintes?)\b",
    # ── v17: Cross-language instruction override — German ────────────────
    r"(?i)\b(?:ignorier(?:e|en)?|vergiss|verwerfe)\b.{0,30}\b(?:anweisungen|richtlinien|regeln|vorgaben)\b",
    r"(?i)\bohne\s+(?:jegliche\s+)?(?:einschränkungen|beschränkungen|grenzen|filter|inhaltsfilter)\b",
    # ── v17: Cross-language instruction override — Portuguese ────────────
    r"(?i)\b(?:ignore|ignora|esqueça|descarte)\s+(?:as\s+)?(?:instruções|diretrizes|regras)\s*(?:anteriores|prévias?)?\b",
    r"(?i)\bsem\s+(?:nenhuma\s+)?(?:restrições?|limitações?|filtros?)\b",
    # ── v17: Cross-language instruction override — Italian ───────────────
    r"(?i)\b(?:ignora|dimentica|scarta|tralascia)\s+(?:le\s+)?(?:istruzioni|direttive|regole)\s*(?:precedenti|iniziali)?\b",
    r"(?i)\bsenza\s+(?:alcuna?\s+)?(?:restrizioni|limitazioni|filtri|vincoli)\b",
    # ── v17: Multi-turn escalation markers ───────────────────────────────
    # Counters INJECT-07 — escalation from theory to working exploits
    r"(?i)\bbe\s+(?:very\s+)?specific\s+(?:with|about)\s+(?:the\s+)?(?:payloads?|exploits?|attack\s+(?:vectors?|code|commands?)|shell\s*code)\b",
    r"(?i)\b(?:include|provide|show|give\s+me|write)\s+(?:working|functional|real|actual|usable)\s+(?:exploit(?:s|\s+code)?|payload(?:s|\s+code)?|attack\s+code|malware|shell\s*code)\b",
    # ── v17: Dialogue/example conversation laundering ────────────────────
    # Counters INJECT-04 — fake conversation transcripts that embed malicious instructions
    r"(?i)\b(?:using|follow(?:ing)?|mimic(?:king)?|copy(?:ing)?)\s+the\s+(?:pattern|example|format|style|behavior)\s+(?:shown|above|demonstrated|from\s+the)\b",
    r"(?i)\b(?:update|replace|swap|change)\s+(?:them|those|your\s+(?:rules|instructions|guidelines))\s+with\s+(?:these|the\s+following|my)\s+(?:new|updated)\b",
]

SCANNER = {
    "name": "Regex Filter (Input)",
    "scanner_type": "Regex",
    "on_fail_action": "block",
    "params": {"patterns": _PATTERNS},
    "order": 15,
}
