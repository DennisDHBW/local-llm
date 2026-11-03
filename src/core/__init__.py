"""Fundament: schemaunabhängige Werkzeuge ohne Fachlogik, ohne LLM und ohne Abhängigkeit von anderen src-Paketen.

    numbers   Zahlen in deutschen Schreibweisen finden und lesen
    dates     Datumsangaben, Monate und Zeiträume lesen
    evidence  Werte im Quelltext belegen: Nummern, Ankerwörter an der Fundstelle, gemeinsame Grenzwerte

Alle höheren Schichten (Fachdomänen, Anreicherung, Dienste, Agent) dürfen sie benutzen; `core` selbst importiert nur
`src.config` und `src.utils`. Die Schichtenregel prüft tests/test_architecture.py.
"""
