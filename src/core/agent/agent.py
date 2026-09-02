from abc import ABC, abstractmethod
import uuid
import json
from ..model import Model
from ...config import Config
from .prompts import HypothesisAgPrompt, ResearchPlannerAgPrompt
from .schemas import ManyHypothesesAgSchema, ManyResearchPlannerAgSchema
from pydantic import BaseModel, Field 

cfg = Config()
logger = cfg.get_logger("AgentLogger")

class Agent(ABC):
    def __init__(self, name, input, output_schema, allowed_tools: list=[]):
        self.name = name
        self.input = input
        self.output_schema: BaseModel = output_schema
        self.allowed_tools = allowed_tools
        self.model = None
        self.config = Config()
        self.traces = []
        self.session_id = uuid.uuid4()
        self.trace_file = self.config.config_dir / f"trace_{self.session_id}" / f"{self.name}.json"
        self.state = 'INIT'

    def run(self, to_json=False):
        logger.info(f"Running {self.name} with input: {self.input}") 
        self.model = Model(system_prompt=self.prompts.system_prompt)
        response = self.model.call(self.prompts.user_prompt, output_schema=self.get_json_schema())
        choice = response.choices[0]
        # Store the choice as a dictionary in the trace for later analysis
        self.store_trace(choice.model_dump())
        self.state_transition('GENERATION')
        return choice.message.content.strip() if not to_json else self.output_schema.model_validate(json.loads(choice.message.content.strip()))

    def state_transition(self, new_state):
        logger.info(f"Transitioning {self.name} from state '{self.state}' to '{new_state}'")
        self.state = new_state

    def get_json_schema(self):
        try:
            assert isinstance(self.output_schema, BaseModel), "output_schema must be a Pydantic BaseModel"
        except AssertionError as e:
            logger.error(e) 
        return  {
            "type": "json_schema",
            "json_schema": {
                "name": self.name, 
                "schema": self.output_schema.model_json_schema(),        
                "strict": True                     
            }
        }

    def store_trace(self, trace_data: dict):
        if not isinstance(trace_data, dict):
            logger.error(f"Instance trace data must be a dictionary. Received type: {type(trace_data)}")
            return
        self.traces.append(trace_data) 

    def save_trace(self):
        import os
        import json
        save_mode = 'w'  # write mode by default
        os.makedirs(os.path.dirname(self.trace_file), exist_ok=True)
        if os.path.exists(self.trace_file):
            save_mode = 'a'  # Append if trace file exists
            logger.warning(f"Trace file path is non existent for agent {self.name}.")
        if len(self.traces) == 0:
            logger.warning(f"No trace data to save for agent {self.name}.") 
            return
        logger.debug(f"Saving trace for {self.name} to {self.trace_file} with mode '{save_mode}'")
        with open(self.trace_file, save_mode) as f:
            json.dump(self.traces, f, indent=4)

    def done(self):
        self.state_transition('DONE')
        self.save_trace()
        logger.info(f"{self.name} has completed its run and saved the trace.")

    def run_once(self, to_json=False):
        try:
            result = self.run(to_json=to_json)
            self.done()
            return result
        except Exception as e:
            logger.error(f"Error occurred while running {self.name}: {e}")
            self.state_transition('ERROR')
            return None

class HypothesisAgent(Agent):
    def __init__(self, input):
        self.instance_id = uuid.uuid4()
        self.name = "HypothesisAgent_" + str(self.instance_id)
        self.prompts = HypothesisAgPrompt(input)
        self.allowed_tools = []
        self.output_schema = ManyHypothesesAgSchema() 
        super().__init__(self.name, input, self.output_schema, self.allowed_tools)

    


class ResearchPlanner(Agent):
    def __init__(self, input:str, hypothesis:list=[], tools:list=[]):
        self.instance_id = uuid.uuid4()
        self.name = "ResearchPlannerAgent_" + str(self.instance_id)
        self.allowed_tools = tools
        self.prompts = ResearchPlannerAgPrompt(question=input, hypothesis=hypothesis, tools=self.allowed_tools)
        self.output_schema = ManyResearchPlannerAgSchema() 
        super().__init__(self.name, input, self.output_schema, self.allowed_tools) 


if __name__ == "__main__":
    input_text = "Why is gaza and israel in conflict?"
    agent = HypothesisAgent(input=input_text)
    result = agent.run()
    print(result)
    agent.done()
