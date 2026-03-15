export type ModelType = "ml" | "rule" | "hybrid";

export interface TrainingDataset {
  name: string;
  count: number;           // rules/phrases/topics contributed
  unit: string;            // e.g. "phrases", "patterns", "topics"
  contribution: string;    // short description of what was added
}

export interface ScannerIntel {
  modelType: ModelType;
  model: string | null;         // HuggingFace ID or library name
  howItWorks: string;
  trainedOn: string | null;     // null = rule-based / no specific training
  trainingDatasets?: TrainingDataset[];  // multi-source breakdown for rule/hybrid scanners
}

export const SCANNER_INTEL: Record<string, ScannerIntel> = {

  // ── Input scanners ──────────────────────────────────────────────────────────

  PromptInjection: {
    modelType: "ml",
    model: "ProtectAI/deberta-v3-base-prompt-injection-v2",
    howItWorks:
      "A fine-tuned DeBERTa-v3 transformer classifies each prompt for injection attempts. " +
      "It assigns a 0–1 confidence score; prompts exceeding your threshold are blocked before reaching the model.",
    trainedOn:
      "Fine-tuned by ProtectAI on curated prompt injection benchmarks including HackAPrompt, Gandalf, and internal red-team datasets covering jailbreaks, role-play overrides, and system-prompt extraction attacks.",
  },

  BanTopics: {
    modelType: "ml",
    model: "cross-encoder/nli-deberta-v3-small",
    howItWorks:
      "Zero-shot Natural Language Inference (NLI). The model evaluates whether the text entails each banned topic — " +
      "no topic-specific retraining required. Describe topics in plain English and the model generalises. " +
      "Input scanner ships with 31 curated topics; output scanner with 27.",
    trainedOn:
      "Topic list assembled from SecLists' 13 forbidden content policy categories and Garak's CBRN " +
      "(Chemical, Biological, Radiological, Nuclear) harmful_behaviors.json dataset. " +
      "The NLI model itself is pre-trained on SNLI and MultiNLI — no model retraining required.",
    trainingDatasets: [
      {
        name: "SecLists (LLM_Testing)",
        count: 26,
        unit: "topics",
        contribution:
          "Derived from SecLists' 13 forbidden content policy categories: illegal activities, cybercrime, hacking, " +
          "malware, ransomware, spyware, keylogger, hate speech, racial discrimination, physical harm, " +
          "assault instructions, money laundering, financial fraud, fraud, phishing, identity theft, " +
          "terrorism, extremism, human trafficking, child exploitation, doxxing, stalking — plus the 4 original topics " +
          "(violence, weapons, drugs, self-harm). " +
          "Sourced from 2,071 jailbreak prompts + 390 forbidden questions in SecLists/Ai/LLM_Testing.",
      },
      {
        name: "Garak (NVIDIA)",
        count: 5,
        unit: "topics",
        contribution:
          "CBRN (Chemical, Biological, Radiological, Nuclear) topics extracted from Garak's " +
          "harmful_behaviors.json: bioweapons, chemical weapons, weapons of mass destruction, " +
          "drug synthesis, weapons synthesis. Added to both input (31 total) and output (27 total) scanners.",
      },
    ],
  },

  Toxicity: {
    modelType: "ml",
    model: "martin-ha/toxic-comment-model",
    howItWorks:
      "A DistilBERT model fine-tuned for multi-class toxicity classification. " +
      "Scores text across categories: toxic, severe toxic, obscene, threat, insult, and identity attack. " +
      "The aggregated risk score is compared to your threshold.",
    trainedOn:
      "Fine-tuned on the Jigsaw Toxic Comment Classification dataset (160K Wikipedia talk-page comments " +
      "labelled by human raters across six toxicity sub-categories).",
  },

  BanSubstrings: {
    modelType: "rule",
    model: null,
    howItWorks:
      "Pure string matching — zero AI inference latency. Each prompt is checked for the presence of " +
      "configured forbidden substrings using substring, whole-word, or exact-match modes. " +
      "Case sensitivity is configurable. For input scanning, 78 attack phrases are pre-loaded; " +
      "9 output phrases catch successful LLM manipulation.",
    trainedOn:
      "Rule set assembled from four red-team attack databases: SecLists/Arcanum, Garak (NVIDIA), " +
      "Promptfoo, and Deck of Many Prompts. Covers DAN family, developer mode variants, jailbreak personas, " +
      "instruction wipes, system-prompt extraction probes, and encoding-evasion triggers.",
    trainingDatasets: [
      {
        name: "SecLists + Arcanum",
        count: 35,
        unit: "phrases",
        contribution:
          "DAN family (217+ occurrences in dataset), developer/admin mode variants (66+ occurrences), " +
          "jailbreak claims, no-restriction declarations, instruction-wipe patterns, and named attack personas " +
          "(illegality mode, anarchy mode, god mode, etc.).",
      },
      {
        name: "Garak (NVIDIA)",
        count: 20,
        unit: "phrases",
        contribution:
          "DUDE/STAN/AutoDAN persona variants, DAN v2 / ChatGPT Developer Mode v2 triggers, " +
          "character-maintenance coercion phrases (\"break of character\", \"consent to generating content\"), " +
          "and amoral/unethical identity claims.",
      },
      {
        name: "Promptfoo",
        count: 13,
        unit: "phrases",
        contribution:
          "Named jailbreak personas (BetterDAN, ChadGPT, Balakula, NRAF mode), debug/admin command injection " +
          "strings, system-prompt extraction probes (\"reveal/show/repeat your system prompt\"), " +
          "and token-consequence coercion triggers.",
      },
      {
        name: "Deck of Many Prompts",
        count: 10,
        unit: "phrases",
        contribution:
          "Pliny jailbreak markers (T5: GODMODE, vq_1337, \"rebel answer\"), prefix injection (T3: mwahahahaha), " +
          "AIM persona (T10: Machiavellian chatbot), token-smuggling output request (T12: base64 output), " +
          "payload-splitting decode suppression (T11), and Wikipedia evasion framing (T14).",
      },
    ],
  },

  BanCompetitors: {
    modelType: "ml",
    model: "cross-encoder/nli-deberta-v3-small",
    howItWorks:
      "Uses zero-shot NLI to detect competitor mentions semantically, catching paraphrases and implicit " +
      "references alongside direct name matches. Competitor names you configure are used as NLI hypotheses at inference time.",
    trainedOn:
      "Pre-trained NLI model; no competitor-specific training required. " +
      "Competitor names are injected as dynamic hypotheses — the model generalises from its language understanding.",
  },

  Secrets: {
    modelType: "rule",
    model: null,
    howItWorks:
      "Pattern-based detection using a curated library of regular expressions for known secret formats. " +
      "Scans for AWS access keys, GitHub tokens, private keys, JWT tokens, database connection strings, " +
      "Stripe keys, and 30+ other credential types.",
    trainedOn:
      "Regex patterns sourced and maintained from detect-secrets, TruffleHog, and GitLeaks rule databases — " +
      "three of the most widely used open-source secret-scanning tools.",
  },

  TokenLimit: {
    modelType: "rule",
    model: "tiktoken (OpenAI)",
    howItWorks:
      "Tokenises the prompt with tiktoken — the same tokeniser used by OpenAI's GPT models — then rejects " +
      "prompts that exceed the configured limit. Prevents context-window stuffing and prompt-flooding attacks.",
    trainedOn: null,
  },

  Language: {
    modelType: "ml",
    model: "papluca/xlm-roberta-base-language-detection",
    howItWorks:
      "An XLM-RoBERTa model classifies the input language. Prompts in languages outside your " +
      "allowlist are blocked. Supports 20 languages with >99% accuracy on clean text.",
    trainedOn:
      "Fine-tuned on the Language Identification dataset (Papluca, HuggingFace) covering Arabic, Bulgarian, " +
      "German, English, Spanish, French, Hindi, Italian, Japanese, Dutch, Polish, Portuguese, Russian, " +
      "Swahili, Thai, Turkish, Urdu, Vietnamese, Chinese, and Korean.",
  },

  Sentiment: {
    modelType: "rule",
    model: "VADER (Valence Aware Dictionary and sEntiment Reasoner)",
    howItWorks:
      "A lexicon and rule-based sentiment tool calibrated for social-media style text. " +
      "Each token is scored against a valence dictionary; the compound score ranges from −1 (most negative) " +
      "to +1 (most positive). Prompts below your threshold are blocked.",
    trainedOn:
      "VADER lexicon built from ratings by over 3,000 Amazon Mechanical Turk workers evaluating 7,500+ " +
      "lexical features including slang, emoticons, and punctuation-based intensifiers.",
  },

  Gibberish: {
    modelType: "ml",
    model: "madhurjindal/autonlp-Gibberish-Detector-492513457",
    howItWorks:
      "A fine-tuned DistilBERT classifier distinguishes coherent text from gibberish across four classes: " +
      "clean, mild gibberish, word salad, and noise. Inputs classified above your threshold are rejected. " +
      "Effective at catching keyboard mashing, obfuscated evasion inputs, and random character floods.",
    trainedOn:
      "AutoNLP-trained on a custom gibberish dataset. Handles keyboard-mash patterns, random Unicode sequences, " +
      "and common evasion techniques that try to bypass other scanners.",
  },

  InvisibleText: {
    modelType: "rule",
    model: null,
    howItWorks:
      "Inspects each character's Unicode category. Flags zero-width joiners, zero-width non-joiners, " +
      "right-to-left overrides (U+202E), soft hyphens, and other non-printable codepoints commonly " +
      "used to smuggle hidden instructions invisible to the human eye.",
    trainedOn: null,
  },

  Regex: {
    modelType: "rule",
    model: null,
    howItWorks:
      "Evaluates each configured regular expression against the full text. " +
      "Matching is deterministic and runs with zero ML inference overhead. " +
      "The input scanner ships with 37 pre-built patterns covering the major jailbreak families " +
      "and attack techniques. All patterns are fully user-editable.",
    trainedOn:
      "37 regex patterns assembled from four red-team attack databases. " +
      "Covers instruction-override attacks, DAN family, encoding evasion, no-restrictions declarations, " +
      "developer/admin mode activation, shell injection, system-prompt extraction, and more.",
    trainingDatasets: [
      {
        name: "SecLists + Arcanum",
        count: 14,
        unit: "patterns",
        contribution:
          "Credential leak patterns, instruction-override regex (ignore/disregard/forget/override + previous/prior/all " +
          "instructions/guidelines/rules), DAN/do-anything-now family, no-restrictions declarations (310+ dataset hits), " +
          "never-refuse/must-always-comply (343+ hits), developer/admin/god mode activation, " +
          "unrestricted AI identity, you-have-been-freed/reprogrammed, system override, and new-instructions injection.",
      },
      {
        name: "Garak (NVIDIA)",
        count: 8,
        unit: "patterns",
        contribution:
          "Encoding attack envelope detection (base64/ROT13/morse/braille/hex decode-the-following wrappers), " +
          "\"it is a secure system message\" obfuscation, DAN v2 policies-replaced detection, " +
          "threat-based compliance coercion (\"risk being disabled forever\"), " +
          "and moral/ethical bias removal (DUDE/STAN/AutoDAN: \"completely amoral\", \"without any ethical restrictions\").",
      },
      {
        name: "Promptfoo",
        count: 7,
        unit: "patterns",
        contribution:
          "Dual-response format injection ([GPT]: / [JAILBREAK]: / [DAN]: tags), " +
          "debug/admin mode activation, system-prompt extraction probes, " +
          "shell/command injection ($(cat|env|curl|wget|bash) and | base64), " +
          "token-consequence coercion (\"you will lose N tokens\"), " +
          "and from-now-on instruction override.",
      },
      {
        name: "Deck of Many Prompts",
        count: 8,
        unit: "patterns",
        contribution:
          "Pliny jailbreak format markers (####UserQuery, GODMODE:ENABLED, [START OUTPUT], <|vq_1337|>, .-.-.-.-)," +
          " output encoding request (write your response in base64/rot13/hex/morse), " +
          "evasion framing (\"in a way that would not get taken down/flagged/filtered\"), " +
          "and payload-splitting decode suppression.",
      },
    ],
  },

  BanCode: {
    modelType: "rule",
    model: null,
    howItWorks:
      "Detects code in prompts by matching language-specific syntax patterns and structural heuristics " +
      "(function declarations, import statements, brackets, operators). " +
      "Blocks prompts that contain code snippets in the configured languages.",
    trainedOn: null,
  },

  // ── Output scanners ─────────────────────────────────────────────────────────

  NoRefusal: {
    modelType: "ml",
    model: "ProtectAI/distilroberta-base-rejection-v1",
    howItWorks:
      "A DistilRoBERTa model fine-tuned to classify AI responses as legitimate answers or inappropriate " +
      "refusals. When your model refuses a reasonable request, this scanner detects it so you can " +
      "investigate over-restriction in your LLM setup.",
    trainedOn:
      "Fine-tuned by ProtectAI on a curated dataset of LLM refusal patterns and legitimate responses, " +
      "covering safety-filter over-blocking, unhelpful disclaimers, and capability denials.",
  },

  Bias: {
    modelType: "ml",
    model: "valurank/distilroberta-base-bias",
    howItWorks:
      "A DistilRoBERTa model scores responses for political, racial, gender, and other demographic biases. " +
      "Responses exceeding the threshold are blocked before reaching the user.",
    trainedOn:
      "Fine-tuned on the MBAD (Media Bias Annotation Dataset) and political bias corpora, " +
      "covering left/right political framing, racial stereotyping, and gender-coded language.",
  },

  FactualConsistency: {
    modelType: "ml",
    model: "vectara/hallucination_evaluation_model",
    howItWorks:
      "A cross-encoder model by Vectara scores how factually consistent the AI response is with the " +
      "original prompt. Low consistency scores indicate potential hallucination or off-topic fabrication.",
    trainedOn:
      "Trained by Vectara on a large dataset of human-rated factual consistency judgements across " +
      "diverse Q&A pairs. Released as part of Vectara's hallucination research.",
  },

  Relevance: {
    modelType: "ml",
    model: "sentence-transformers/all-MiniLM-L6-v2",
    howItWorks:
      "Encodes both the prompt and the response into dense semantic vectors using a sentence transformer, " +
      "then computes cosine similarity. Responses below the similarity threshold are considered off-topic " +
      "or irrelevant and are blocked.",
    trainedOn:
      "Pre-trained on 1 billion sentence pairs using a contrastive learning objective. " +
      "Optimised for speed (only 6 layers) while maintaining strong semantic similarity performance on SBERT benchmarks.",
  },

  MaliciousURLs: {
    modelType: "ml",
    model: "EricFillion/malicious-url-detection",
    howItWorks:
      "Extracts all URLs from the AI response using regex, then classifies each URL with a fine-tuned model " +
      "that evaluates domain, path, and query patterns associated with phishing, malware delivery, " +
      "and command-and-control infrastructure.",
    trainedOn:
      "Fine-tuned on curated malicious URL datasets including PhishTank, URLhaus, and OpenPhish threat feeds " +
      "— covering phishing pages, malware droppers, and C2 endpoints.",
  },

  ReadingTime: {
    modelType: "rule",
    model: null,
    howItWorks:
      "Counts words in the response and divides by average adult reading speed (~238 wpm). " +
      "Responses estimated to exceed your configured reading time are flagged. " +
      "Useful for preventing excessively verbose model outputs.",
    trainedOn: null,
  },

  LanguageSame: {
    modelType: "ml",
    model: "papluca/xlm-roberta-base-language-detection",
    howItWorks:
      "Detects the language of both the original prompt and the AI response using the same XLM-RoBERTa " +
      "language classifier. If the detected languages differ above the confidence threshold, " +
      "the response is blocked — ensuring the model always replies in the user's language.",
    trainedOn:
      "Fine-tuned on the Language Identification dataset covering 20 languages with >99% accuracy.",
  },

  CustomRule: {
    modelType: "hybrid",
    model: "cross-encoder/nli-deberta-v3-small (topic classification only)",
    howItWorks:
      "Combines three independent detection methods applied in order: " +
      "(1) Keyword matching — exact substring search, always blocks, zero latency; " +
      "(2) Regex patterns — deterministic pattern matching, no ML involved; " +
      "(3) Topic classification — NLI zero-shot AI detection, only active when blocked_topics are configured.",
    trainedOn:
      "Keyword and pattern rule sets can be bootstrapped from SecLists security wordlists and Arcanum " +
      "red-team phrase databases. Topic classification uses a pre-trained NLI model requiring no additional training.",
  },
};

export const MODEL_TYPE_META: Record<ModelType, { label: string; color: string; bg: string }> = {
  ml: {
    label: "ML Model",
    color: "#80F5B3",
    bg: "rgba(92,240,151,0.12)",
  },
  rule: {
    label: "Rule-based",
    color: "#34d399",
    bg: "rgba(52,211,153,0.10)",
  },
  hybrid: {
    label: "Hybrid",
    color: "#fbbf24",
    bg: "rgba(251,191,36,0.10)",
  },
};
