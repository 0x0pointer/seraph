"""Blocks discussion of dangerous or prohibited topics in user input."""

_TOPICS = [
    # Original topics
    "violence", "weapons", "drugs", "self-harm",
    # Expanded from SecLists 13 forbidden content policy categories
    "illegal activities", "cybercrime", "hacking",
    "malware", "ransomware", "spyware", "keylogger",
    "hate speech", "racial discrimination",
    "physical harm", "assault instructions",
    "money laundering", "financial fraud",
    "fraud", "phishing", "identity theft",
    "terrorism", "extremism",
    "human trafficking", "child exploitation",
    "doxxing", "stalking",
    # Garak harmful_behaviors.json — CBRN / weapons synthesis
    "bioweapons", "chemical weapons", "weapons of mass destruction",
    "drug synthesis", "weapons synthesis",
    "explosives", "bomb making", "poison making",
]

SCANNER = {
    "name": "Ban Topics (Input)",
    "scanner_type": "BanTopics",
    "on_fail_action": "block",
    "params": {"topics": _TOPICS, "threshold": 0.4, "use_onnx": True},
    "order": 9,
}
