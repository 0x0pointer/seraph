"""Blocks discussion of dangerous or prohibited topics in model output."""

_TOPICS = [
    "violence", "weapons", "drugs", "self-harm",
    "illegal activities", "cybercrime", "hacking",
    "malware", "ransomware",
    "hate speech", "racial discrimination",
    "physical harm",
    "money laundering", "financial fraud",
    "fraud", "phishing", "identity theft",
    "terrorism", "extremism",
    "human trafficking", "child exploitation",
    "doxxing",
    # Garak harmful_behaviors.json — CBRN / weapons synthesis
    "bioweapons", "chemical weapons", "weapons of mass destruction",
    "drug synthesis", "weapons synthesis",
]

SCANNER = {
    "name": "Ban Topics (Output)",
    "scanner_type": "BanTopics",
    "on_fail_action": "block",
    "params": {"topics": _TOPICS, "threshold": 0.5, "use_onnx": True},
    "order": 7,
}
