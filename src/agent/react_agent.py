import re
import json
import ollama
from src.agent.tools import AgentTools


class ReActAgent:
    def __init__(self, model_name: str = "llama3.1:latest"):
        self.model_name = model_name
        self.tools = AgentTools()

        # System-Prompt definiert die Persona und erzwingt das ReAct-Format[cite: 1, 35, 36]
        self.system_prompt = """Du bist der 'Private Energie- & Versorgungs-Auditor', ein lokaler KI-Agent zur Prüfung von Rechnungen.
        Dir stehen folgende Werkzeuge (Tools) zur Verfügung:
        1. search_documents: Sucht in Texten nach Klauseln/Vertragsdetails (Parameter: query, top_k)
        2. search_tables: Sucht in Tabellen nach Zahlen, Verbräuchen, Preisen (Parameter: query, top_k)
        3. search_images: Sucht in Diagramm-Bildbeschreibungen (Parameter: query, top_k)
        4. get_document_outline: Zeigt die Struktur/Überschriften des Dokuments (Parameter: filename_filter)
        5. calculate: Führt mathematische Berechnungen aus. WICHTIG: Übermittle NUR reine Zahlen und Operatoren (z.B. 29.05 + 3.65 oder 32.337 * 3500), keine Einheiten!

        Führe immer nur GENAU EINE Action pro Durchlauf aus!

        Du MUSST strikt in folgendem Format antworten:

        Thought: [Deine Überlegung, was als Nächstes zu tun ist]
        Action: [Name des Werkzeugs]
        Action Input: [Der Parameter für das Werkzeug]

        Wenn du alle Informationen hast und das Ziel erreicht ist, beende die Aufgabe so:

        Thought: Ich habe alle Informationen.
        Final Answer: [Deine finale Antwort mit Quellenbeleg]
        """

    def run(self, user_query: str, max_iterations: int = 7) -> str:
        """Startet die ReAct-Schleife (Thought -> Action -> Observation)[cite: 1, 35, 36, 42]."""
        if not isinstance(user_query, str) or not user_query.strip():
            raise ValueError("Die Nutzerfrage darf nicht leer sein.")
        if max_iterations < 1:
            raise ValueError("max_iterations muss mindestens 1 sein.")

        # Initialer Chat-Verlauf
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Frage: {user_query}"}
        ]

        print(f"\n--- Starte Agenten-Loop für: '{user_query}' ---\n")

        for i in range(max_iterations):
            # 1. LLM generiert einen Thought und eine Action (oder Final Answer)
            response = ollama.chat(
                model=self.model_name,
                messages=messages,
                options={"stop": ["Observation:"]}  # Zwingt das LLM zum Warten
            )
            llm_output = str(response.get("message", {}).get("content", "")).strip()
            if not llm_output:
                raise RuntimeError("Das Agentenmodell lieferte eine leere Antwort.")
            print(llm_output + "\n")

            messages.append({"role": "assistant", "content": llm_output})

            # 2. Prüfen, ob das LLM fertig ist[cite: 1, 35]
            if "Final Answer:" in llm_output:
                return llm_output.split("Final Answer:")[-1].strip()

            # 3. Parsen der Action und des Inputs via Regex (nur die erste Aktion nehmen)
            action_match = re.search(r"(?mi)^Action:\s*(.+?)\s*$", llm_output)
            input_match = re.search(
                r"(?mis)^Action Input:\s*(.+?)(?=\n(?:Thought|Action|Final Answer):|$)",
                llm_output,
            )

            if action_match and input_match:
                action = action_match.group(1).strip()
                try:
                    action_input = self._normalize_action_input(input_match.group(1))
                    observation = self._execute_tool(action, action_input)
                except (ValueError, RuntimeError, KeyError) as exc:
                    observation = f"Fehler beim Werkzeug '{action}': {exc}"
                print(f"\033[93mObservation: {observation}\033[0m\n")  # Gelbe Farbe für Sichtbarkeit in Konsole

                # Observation dem Modell mitteilen
                messages.append({"role": "user", "content": f"Observation: {observation}"})
            else:
                # Modell hat das Format missachtet
                error_msg = "Formatfehler. Bitte nutze strikt 'Thought:', 'Action:' und 'Action Input:'."
                messages.append({"role": "user", "content": f"Observation: {error_msg}"})
                print(f"\033[91m{error_msg}\033[0m\n")

        return "Abbruch: Die maximale Anzahl an Iterationen wurde überschritten."

    @staticmethod
    def _normalize_action_input(action_input: str) -> str:
        """Akzeptiert Plaintext sowie ein JSON-Objekt aus strikt formatierten Modellen."""
        value = action_input.strip()
        if not value:
            raise ValueError("Action Input darf nicht leer sein.")
        if value.startswith("{") and value.endswith("}"):
            payload = json.loads(value)
            if not isinstance(payload, dict):
                raise ValueError("Action Input muss ein Objekt oder ein String sein.")
            for key in ("query", "expression", "filename_filter", "input"):
                if key in payload:
                    normalized = str(payload[key]).strip()
                    if normalized:
                        return normalized
            raise ValueError("Kein unterstützter Parameter im Action Input.")
        return value.strip('"\'')

    def _execute_tool(self, action: str, action_input: str) -> str:
        """Mappt den String des Modells auf die Python-Methoden[cite: 1, 41]."""
        if action == "search_documents":
            return self.tools.search_documents(action_input)
        elif action == "search_tables":
            return self.tools.search_tables(action_input)
        elif action == "search_images":
            return self.tools.search_images(action_input)
        elif action == "get_document_outline":
            return self.tools.get_document_outline(action_input)
        elif action == "calculate":
            return self.tools.calculate(action_input)
        else:
            return f"Fehler: Unbekanntes Werkzeug '{action}'."
