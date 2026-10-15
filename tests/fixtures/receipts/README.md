Testbons (Kassenbelege) für die Domäne `receipt`.

- `*_ocr.txt`: Zeilen, wie die OCR (RapidOCR, Zeilenrekonstruktion über Box-Koordinaten) sie aus den
  Bildschirmfotos der digitalen Bons liest - mit echten OCR-Fehlern (`1, 25`, `2,38B`, `0,25） 12`, `A7%`,
  fehlende Umlaute, Logo nicht lesbar). Nicht korrigieren: genau diese Fehler muss der Parser aushalten.
- Die Bons enthalten keine personenbezogenen Daten (Filialadresse, Artikel, Beträge).
- Rohfassung: zweifache Auflösung und OHNE die Betragsreparatur, die der Parser im Zeilenmodus anwendet
  (`1, 25` -> `1,25`). Der Domänen-Parser muss beide Fassungen lesen; `tests/test_receipts.py` prüft das.
- Erwartungswerte in den Tests stammen von den Bon-Bildern (Summe, MwSt je Satz, Rabatte, Pfand).
