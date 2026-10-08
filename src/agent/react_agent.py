import re
import json
import ollama
from typing import Callable, Optional
from src.agent.tools import AgentTools


class ReActAgent:
    def __init__(self, model_name: str = "llama3.1:latest"):
        self.model_name = model_name
        self.tools = AgentTools()

        self.system_prompt = """Du bist ein präziser, universeller KI-Agent zur Dokumentenanalyse.

Verfügbare Werkzeuge:
1. get_document_inventory: Liefert eine Vollübersicht aller indizierten Dokumente mit Metadaten (Dateinamen, Typen, Datum, Anbieter, Nummern). Parameter: leer lassen.
2. search_documents: Sucht in Textabsätzen nach Klauseln und Begriffen. Parameter: Suchtext.
3. search_tables: Sucht in Tabellenzeilen nach Zahlen, Preisen und Positionen. Parameter: Suchtext.
4. search_images: Sucht in Bild- und Diagrammbeschreibungen. Parameter: Suchtext.
5. get_document_outline: Zeigt die Kapitelstruktur eines Dokuments. Parameter: Dateiname oder leer lassen.
6. calculate: Führt reine mathematische Berechnungen aus. Parameter: NUR Zahlen und Operatoren (z.B. "15.41 + 4.89"). KEINE Texte, Einheiten oder Paragraphenzeichen!

STRUKTUR FÜR DEINE GEDANKEN (Thought):
Gliedere JEDEN Gedankenschritt zwingend wie folgt:
Thought:
- Bisherige Erkenntnisse: [Was weiß ich bereits sicher?]
- Fehlende Fakten: [Welche Information fehlt noch zur Beantwortung?]
- Werkzeug-Wahl: [Warum wähle ich dieses Werkzeug?]
- Eingabe-Muster: [Wie lautet der exakte Suchbegriff oder Rechenausdruck?]

WICHTIGE VERHALTENSREGELN:
- Verwende bei Fragen zu Dokumentanzahl, Typen oder Metadaten im ERSTEN Schritt `get_document_inventory`.
- Unterscheide strikt zwischen 'Verbrauchsabrechnungsnummer' (Rechnungsnummer) und 'Vertragskonto'.
- Beachte bei Preisen: Ein Gesamt-Grundpreis enthält bereits seine Unterpositionen. Addiere nicht doppelt.
- Sobald alle Fakten vorliegen, erstelle DIREKT die `Final Answer`.
- Führe pro Durchlauf strikt nur GENAU EINE Aktion aus.

Antwortformat für Werkzeugaufrufe:
Thought:
- Bisherige Erkenntnisse: ...
- Fehlende Fakten: ...
- Werkzeug-Wahl: ...
- Eingabe-Muster: ...
Action: Werkzeugname
Action Input: Parameterwert

Antwortformat für das Ergebnis:
Thought:
- Bisherige Erkenntnisse: Alle notwendigen Daten liegen vor.
- Final Answer Vorbereitung: Prüfe auf Vollständigkeit.
Final Answer: Reine Faktenantwort mit konkreten Zahlen und Quellen.
"""

    @staticmethod
    def _contains_unresolved_placeholders(text: str) -> bool:
        placeholder_pattern = r"\[[A-Za-z0-9_\s\-\.äöüÄÖÜß]{2,60}\]"
        return bool(re.search(placeholder_pattern, text))

    def run(
        self,
        user_query: str,
        max_iterations: int = 8,
        callback: Optional[Callable[[dict], None]] = None,
        stop_check: Optional[Callable[[], bool]] = None
    ) -> str:
        if not isinstance(user_query, str) or not user_query.strip():
            raise ValueError("Die Nutzerfrage darf nicht leer sein.")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Frage: {user_query}"}
        ]

        last_action_signature = None
        repeat_count = 0

        for i in range(max_iterations):
            iteration_num = i + 1

            # Abbruch durch den Benutzer prüfen
            if stop_check and stop_check():
                return "⚠️ Die Ausführung wurde durch den Benutzer abgebrochen."

            if callback:
                callback({"type": "thinking_start", "iteration": iteration_num})

            response = ollama.chat(
                model=self.model_name,
                messages=messages,
                options={"stop": ["Observation:"]}
            )
            llm_output = str(response.get("message", {}).get("content", "")).strip()
            if not llm_output:
                raise RuntimeError("Das Agentenmodell lieferte eine leere Antwort.")

            action_match = re.search(r"(?mi)^Action:\s*(.+?)$", llm_output)

            if action_match:
                action_pos = action_match.start()
                input_match = re.search(
                    r"(?mis)^Action Input:\s*(.*?)(?=\n(?:Thought|Action|Final Answer):|$)",
                    llm_output[action_pos:]
                )

                if input_match:
                    action = action_match.group(1).strip()
                    raw_input = input_match.group(1)
                    action_input = self._normalize_action_input(raw_input)

                    thought_match = re.search(r"(?mis)^Thought:\s*(.+?)(?=\nAction:|$)", llm_output)
                    thought_text = thought_match.group(1).strip() if thought_match else llm_output[:action_pos].strip()

                    current_signature = f"{action}:{action_input}"
                    if current_signature == last_action_signature:
                        repeat_count += 1
                    else:
                        repeat_count = 0
                        last_action_signature = current_signature

                    if repeat_count >= 1:
                        messages.append({"role": "user", "content": "Observation: Diese Aktion wurde bereits ausgeführt. Erstelle nun deine 'Final Answer' mit den bisherigen Daten."})
                        continue

                    clean_assistant_step = f"Thought:\n{thought_text}\nAction: {action}\nAction Input: {action_input}"
                    messages.append({"role": "assistant", "content": clean_assistant_step})

                    if callback:
                        callback({
                            "type": "action_execution",
                            "iteration": iteration_num,
                            "thought": thought_text,
                            "action": action,
                            "action_input": action_input
                        })

                    try:
                        observation = self._execute_tool(action, action_input)
                    except Exception as exc:
                        observation = f"Fehler beim Werkzeug '{action}': {exc}"

                    messages.append({"role": "user", "content": f"Observation: {observation}"})

                    if callback:
                        callback({
                            "type": "observation_result",
                            "iteration": iteration_num,
                            "observation": observation
                        })
                    continue

            if "Final Answer:" in llm_output:
                final_ans = llm_output.split("Final Answer:")[-1].strip()
                thought_part = llm_output.split("Final Answer:")[0].replace("Thought:", "").strip()

                if self._contains_unresolved_placeholders(final_ans):
                    error_feedback = "Observation: Deine Final Answer enthält ungefüllte Platzhalter. Ersetze sie durch konkrete Daten aus den Observations."
                    messages.append({"role": "assistant", "content": llm_output})
                    messages.append({"role": "user", "content": error_feedback})
                    continue

                messages.append({"role": "assistant", "content": llm_output})

                if callback:
                    callback({
                        "type": "final_answer",
                        "iteration": iteration_num,
                        "thought": thought_part,
                        "final_answer": final_ans
                    })
                return final_ans

            error_msg = "Formatfehler. Bitte strukturiere deine Antwort strikt nach Vorgabe mit 'Thought:', 'Action:', 'Action Input:' ODER 'Final Answer:'."
            messages.append({"role": "assistant", "content": llm_output})
            messages.append({"role": "user", "content": f"Observation: {error_msg}"})

        return "Abbruch: Die maximale Anzahl an Iterationen wurde überschritten."

    @staticmethod
    def _normalize_action_input(action_input: str) -> str:
        value = action_input.strip()
        if not value or value.lower() in ("none", "null", '""', "''"):
            return ""
        if value.startswith("{") and value.endswith("}"):
            try:
                payload = json.loads(value)
                if isinstance(payload, dict):
                    for key in ("query", "expression", "filename_filter", "input"):
                        if key in payload:
                            normalized = str(payload[key]).strip()
                            if normalized:
                                return normalized
                    return ""
            except json.JSONDecodeError:
                pass
        return value.strip('"\'')

    def _execute_tool(self, action: str, action_input: str) -> str:
        clean_action = re.sub(r"\(.*?\)$", "", action.strip().strip("`'\"")).strip()

        if clean_action == "get_document_inventory":
            return self.tools.get_document_inventory()
        elif clean_action == "search_documents":
            return self.tools.search_documents(action_input)
        elif clean_action == "search_tables":
            return self.tools.search_tables(action_input)
        elif clean_action == "search_images":
            return self.tools.search_images(action_input)
        elif clean_action == "get_document_outline":
            return self.tools.get_document_outline(action_input)
        elif clean_action == "calculate":
            return self.tools.calculate(action_input)
        else:
            return f"Fehler: Unbekanntes Werkzeug '{action}'."