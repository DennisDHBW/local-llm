import pytest

import src.agent.chat as chat
from src.agent.chat import ChatSession, QuestionCondenser, Turn


class FakeAgent:
    def __init__(self, answers):
        self.answers = list(answers)
        self.received = []
        self.last_evidence = []

    def run(self, query, max_iterations=6, callback=None, stop_check=None):
        self.received.append(query)
        self.last_evidence = [{"id": "x", "content": "c", "metadata": {"filename": "ZEAG_25.pdf (extrahierte Kerndaten)"}}]
        return self.answers.pop(0)


def patch_llm(monkeypatch, reply):
    prompts = []

    def fake_generate(model=None, prompt="", options=None, **kw):
        prompts.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return {"response": reply}

    monkeypatch.setattr(chat.ollama, "generate", fake_generate)
    return prompts


def test_first_question_goes_unchanged_and_without_llm_call(monkeypatch):
    prompts = patch_llm(monkeypatch, "sollte nie benutzt werden")
    agent = FakeAgent(["Antwort 1"])
    session = ChatSession(agent)
    assert session.ask("  Wie hoch ist der Arbeitspreis in ZEAG_25?  ") == "Antwort 1"
    assert agent.received == ["Wie hoch ist der Arbeitspreis in ZEAG_25?"] and prompts == []


def test_follow_up_is_rewritten_with_history_and_documents(monkeypatch):
    prompts = patch_llm(monkeypatch, "Eigenständige Frage: „Wie hoch ist der Arbeitspreis in ZEAG_25.pdf brutto?“")
    agent = FakeAgent(["Der Arbeitspreis beträgt 28,45 ct/kWh netto [1].\n\nQuellen:\n[1] ZEAG_25.pdf", "Brutto 33,86 ct/kWh."])
    events = []
    session = ChatSession(agent)
    session.ask("Wie hoch ist der Arbeitspreis in ZEAG_25?")
    session.ask("Und brutto?", callback=events.append)

    assert agent.received[1] == "Wie hoch ist der Arbeitspreis in ZEAG_25.pdf brutto?"
    assert "28,45 ct/kWh netto" in prompts[0] and "Quellen:" not in prompts[0]      # Quellenblock nicht im Verlauf
    assert "Dokumente: ZEAG_25.pdf" in prompts[0] and "Neue Frage: Und brutto?" in prompts[0]
    assert events == [{"type": "question_rewritten", "original": "Und brutto?",
                       "standalone": "Wie hoch ist der Arbeitspreis in ZEAG_25.pdf brutto?"}]


@pytest.mark.parametrize("reply", ["", "   \n", "x" * 500, RuntimeError("ollama down"), ConnectionError("down")])
def test_condenser_falls_back_to_original_question(monkeypatch, reply):
    patch_llm(monkeypatch, reply)
    history = [Turn("Frage", "Frage", "Antwort")]
    assert QuestionCondenser().condense(history, "Und brutto?") == "Und brutto?"


def test_condenser_cleans_formatting(monkeypatch):
    patch_llm(monkeypatch, "Frage:\n\"Wie hoch ist der Grundpreis in Berlin2_25.pdf?\"\nErklärung folgt")
    out = QuestionCondenser().condense([Turn("a", "a", "b")], "Und der Grundpreis bei Berlin2?")
    assert out == "Wie hoch ist der Grundpreis in Berlin2_25.pdf?"


def test_failed_or_aborted_answers_are_not_remembered(monkeypatch):
    patch_llm(monkeypatch, "egal")
    agent = FakeAgent(["⚠️ Die Ausführung wurde durch den Benutzer abgebrochen.",
                       "Abbruch: Die maximale Anzahl an Iterationen wurde überschritten.", "", "Gute Antwort"])
    session = ChatSession(agent)
    for q in ("a?", "b?", "c?"):
        session.ask(q)
    assert session.history == []
    session.ask("d?")
    assert [t.answer for t in session.history] == ["Gute Antwort"]


def test_history_is_limited_and_prompt_budget_respected(monkeypatch):
    prompts = patch_llm(monkeypatch, "Neue Frage umformuliert?")
    agent = FakeAgent([f"Antwort {i} " + "y" * 2000 for i in range(8)])
    session = ChatSession(agent, max_turns=3)
    for i in range(8):
        session.ask(f"Frage {i}?")
    assert [t.question for t in session.history] == ["Frage 5?", "Frage 6?", "Frage 7?"]
    assert all(len(p) < chat.MAX_HISTORY_CHARS + 1500 for p in prompts)        # Prompt wächst nicht unbegrenzt


def test_reset_and_validation(monkeypatch):
    patch_llm(monkeypatch, "x")
    session = ChatSession(FakeAgent(["A"]))
    session.ask("Frage?")
    session.reset()
    assert session.history == []
    with pytest.raises(ValueError):
        session.ask("   ")
