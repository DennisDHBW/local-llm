"""Weiche P1/P2: Textregel und Zusammensetzen der Antworten."""

from src.agent.router import route
from src.eval.router_eval import compose


def test_deadline_list_and_comparison_questions_go_to_p2():
    assert route("Welche Kündigungsfrist hat der Heizstromvertrag?").system == "P2"
    assert route("Bis wann muss ich den Vertrag spätestens kündigen?").rule == "frist"
    assert route("Bei welchen Verträgen ist die Preisgarantie abgelaufen?").system == "P2"
    assert route("Welche Rechnungen sind im November 2026 fällig?").rule == "liste"
    assert route("Entspricht der Monatspreis auf der Rechnung dem Preis im Vertrag?").rule == "vergleich"


def test_single_value_questions_stay_with_p1():
    for q in ("Wie hoch ist der monatliche Abschlag im Stromvertrag?", "Welche Kundennummer hat Thomas Kramer?",
              "Welches Fahrzeug ist bei der NordStern Versicherung versichert?", "Wie hoch ist mein Gaspreis pro kWh?"):
        assert route(q).system == "P1", q


def _rec(system, answer, qid="x", question="Wie hoch ist der Abschlag?", latency=10.0):
    return {"system": system, "set": "dev", "qid": qid, "rep": 0, "question": question, "answer": answer,
            "status": "ok", "latency_s": latency}


def test_compose_picks_routed_answer_and_cascade_adds_latency():
    raw = [_rec("P1", "Dazu ist in den vorliegenden Dokumenten nichts belegt."), _rec("P2", "130,00 € [1]"),
           _rec("P1", "a", qid="y", question="Welche Verträge laufen?"), _rec("P2", "b", qid="y", question="Welche Verträge laufen?")]
    rule = {r["qid"]: r for r in compose(raw, "Weiche")}
    assert rule["x"]["answer"].startswith("Dazu") and rule["y"]["answer"] == "b" and rule["y"]["routed_to"] == "P2"
    cascade = {r["qid"]: r for r in compose(raw, "Kaskade")}
    assert cascade["x"]["answer"] == "130,00 € [1]" and cascade["x"]["latency_s"] == 20.0
    assert cascade["y"]["answer"] == "a" and cascade["y"]["routed_to"] == "P1"
