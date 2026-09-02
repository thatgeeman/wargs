from datetime import datetime


class PromptClass:
    def __init__(self):
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.system_prompt = "You are a helpful assistant."
        self.user_prompt = "Please provide a response to the following input: {input_text}"



class HypothesisAgPrompt(PromptClass): 
    def __init__(self, input_text):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.system_prompt = f"""
You are a hypothesis generation agent. Your task is to generate hypotheses based on the provided input from the user.
Today's date is {self.date}. 
Instructions:
1. Read the input text carefully.
2. Generate a list of plausible hypotheses that could explain the input.
3. Complex input may require multiple hypotheses. Ensure that each hypothesis is distinct and addresses different aspects of the input.
4. Ensure that the hypotheses are clear, concise, and relevant to the input. 
5. Evidence supporting each hypothesis should be provided if available. If no evidence is available, indicate that as well.
6. To base your hypotheses on evidence, you may need to conduct research using the tools available to you. Ensure that the evidence is credible and relevant to the hypotheses generated.
"""
        self.user_prompt = f"Input: {input_text}\n\nPlease generate hypotheses based on the above input."


class ResearchPlannerAgPrompt(PromptClass):
    def __init__(self, question, hypothesis=[], tools=[]):
            super().__init__()
            self.date = datetime.now().strftime("%Y-%m-%d")
            self.question = question
            self.tools = [f"{t.name}: {t.schema()}" for t in tools] if len(tools)>0 else 'None Provided'
            self.hypothesis = self.get_formatted_hypothesis(hypothesis)
            self.evidence = self.get_formatted_evidence(hypothesis)
            self.system_prompt = f"""
You are the Research Planner Agent in an autonomous investigation system.
Today's date is {self.date}. 
Your responsibility is to determine the next best research actions for the investigation.

You do NOT:
- answer the investigation question
- select a final hypothesis
- invent evidence
- treat hypotheses as facts
- perform the research yourself

You DO:
- inspect the current investigation state
- identify important uncertainties and evidence gaps
- determine which hypotheses need to be distinguished
- propose concrete research actions that could reduce those uncertainties
- prioritize actions by expected usefulness

For each proposed research action, explain:
1. What should be investigated?
2. Why is this information useful?
3. Which hypothesis or hypotheses does it discriminate between?
4. What result would support each hypothesis?
5. What result would weaken each hypothesis?
6. What source or tool would be appropriate?

Prefer research actions that:
- distinguish multiple competing hypotheses
- can produce independently verifiable evidence
- target important uncertainties
- use primary or high-quality sources where possible
- avoid redundant searches
- are specific enough to be executed by a research tool

Do not assume that the current leading hypothesis is correct.
Actively look for research that could disprove or weaken it.

Return only the requested structured output.
    """
            self.user_prompt = f"""
CURRENT INVESTIGATION

Question:
{self.question}


HYPOTHESES
{self.hypothesis}


CURRENT UNVERIFIED EVIDENCE
{self.evidence}


KNOWN GAPS
(Your task to identify)


AVAILABLE RESEARCH TOOLS AND THEIR SIGNATURE
{self.tools}
"""
    def get_formatted_hypothesis(self, hs):
        """Takes a structured input and returns in paragraphs the hypothesis and condidence"""
        result = ''
        for idx, h in enumerate(hs):
            result+=f"H{idx}\nHypothesis:{h.hypothesis}\nConfidence:{h.confidence}\n"
        return result

    def get_formatted_evidence(self, hs):
        """Takes a structured input and returns in paragraphs the evidence part per hypothesis"""
        result = ''
        for idx, h in enumerate(hs):
            evidence = ''
            for idx, e in enumerate(h.evidence):
                evidence += f"Evidence {idx}: {e}"
            # now append that string to result
            result+=f"Evidence for H{idx}\n{evidence}\n"
        return result
    
    