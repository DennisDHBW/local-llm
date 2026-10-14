"""Tests für die Tokenisierung und den BM25-Index (Dezimalzahlen müssen ganze Tokens bleiben)."""

from src.retrieval.search import _BM25Index, _tokens


def test_decimal_numbers_stay_whole_tokens():
    assert "28.45" in _tokens("Arbeitspreis 28,45 ct/kWh")
    assert "28" not in _tokens("Arbeitspreis 28,45 ct/kWh")


def test_comma_and_dot_notation_match():
    assert _tokens("28,45") == _tokens("28.45") == ["28.45"]


def test_thousands_separator_is_normalized():
    assert _tokens("Verbrauch 3.512,00 kWh")[1] == "3512.00"


def test_plain_words_are_still_stemmed_and_stopwords_removed():
    tokens = _tokens("Die Preise der Rechnungen")
    assert "die" not in tokens and "der" not in tokens
    assert any(t.startswith("preis") for t in tokens)


def test_bm25_finds_price_by_exact_number():
    docs = [
        "Arbeitspreis: 28,45 ct/kWh netto",
        "Arbeitspreis: 31,10 ct/kWh netto",
        "Grundpreis: 11,70 EUR pro Monat",
    ]
    index = _BM25Index(["a", "b", "c"], docs, [{}, {}, {}])
    scores = index.scores("Arbeitspreis 28,45")
    assert scores[0] > scores[1] > 0
    assert scores[2] == 0.0


def test_bm25_number_does_not_match_fragment():
    index = _BM25Index(["a", "b"], ["Betrag 28,45 EUR", "Seite 28 von 45"], [{}, {}])
    scores = index.scores("28,45")
    assert scores[0] > 0
    assert scores[1] == 0.0
