"""Single Qwen vLLM instance with mandatory JSON-schema constrained decoding."""
from dataclasses import replace
from pathlib import Path


class QwenStructuredBackend:
    def __init__(self, config_path, *, model_path_override=None):
        # Probe API compatibility before allocating GPU memory. No silent text fallback.
        from vllm import SamplingParams
        from vllm.sampling_params import StructuredOutputsParams
        SamplingParams(max_tokens=1, structured_outputs=StructuredOutputsParams(json={'type':'object', 'properties':{}, 'additionalProperties':False}))
        from datamate.planner import VLLMModel, load_config
        config, self.options = load_config(config_path)
        if model_path_override is not None:
            config = replace(config, model_path=Path(model_path_override))
        self.input_budget = config.max_model_len - self.options.max_new_tokens - 64
        if self.input_budget <= 0:
            raise ValueError('no grounding input budget')
        self.model = VLLMModel(config, default_options=self.options)
        self.model.load()
        self.last_generation = {}

    @staticmethod
    def messages(system, user):
        from datamate.planner import ChatMessage
        return [ChatMessage(role='system', content=system), ChatMessage(role='user', content=user)]

    def count_tokens(self, system, user):
        # Count failures are fatal: never assume a prompt fits from a character heuristic.
        return self.model.count_chat_tokens(self.messages(system, user))

    def _run_chat(self, system, user, *, json_schema):
        self.last_generation = {}
        result = self.model.chat(self.messages(system, user), options=replace(self.options, json_schema=json_schema))
        self.last_generation = dict(input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            finish_reason=result.finish_reason, max_new_tokens=self.options.max_new_tokens)
        return result.text

    def chat(self, system, user, schema):
        return self._run_chat(system, user, json_schema=schema)

    def chat_unstructured(self, system, user):
        """Run unconstrained chat on the same loaded 3B model (e.g. Semantic Discovery)."""
        return self._run_chat(system, user, json_schema=None)
