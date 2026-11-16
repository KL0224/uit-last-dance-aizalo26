"""One Qwen proposal per question, deterministic verification, legacy pipeline bridge."""
from __future__ import annotations
import json
import time
from .neo_contracts import Proposal
from .neo_verifier import verify_proposal
from .contracts import GroundedQuestion, QuestionIntent, OperationKind, AnswerTypeHint, CoverageStatus, SelectedSchema

from .compact_proposal import ReferenceMap
from .context_budget import fit_context
from .proposal_recovery import parse_partial_proposal
from .neo_prompt import SYSTEM, PROMPT_VERSION


def planner_hint(payload):
    return ('GROUNDING CONTRACT v2.0. Preserve verified date bounds [start,end), filters, grain and denominators in generation AND repair. '
            'Reference-valid measures and uncertain JOINs still require semantic review against policies. '
            'Unresolved constraints remain requirements: do not silently omit them or invent lunar conversions. '
            'Rejected claims are diagnostics, not active constraints. Reconstruct them from the original question and context. '
            'Measures marked requires_repair and assessment.blocked_refs cannot be used until their missing dependencies are repaired. '
            'Temporal unbound_constraints are calculated evidence only; bind their scope before applying them. '
            'Partial/unknown does not prove unanswerable.\n' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')))


class NeoGroundingEngine:
    def __init__(self, chat_fn, indexes, *, token_count_fn=None, max_input_tokens=5632, debug_model_output=False, compact_proposals=True, structured_chat_fn=None):
        self.chat_fn = chat_fn
        self.compact_proposals = compact_proposals
        self.structured_chat_fn = structured_chat_fn
        self.indexes = indexes
        self.token_count_fn = token_count_fn or (lambda s,u: len((s+u).encode()))
        self.max_input_tokens = max_input_tokens
        self.debug_model_output = debug_model_output
        self.last_diagnostics = {}
        from .value_verifier import ValueVerificationProvider
        self.value_verifiers = {key: ValueVerificationProvider(index) for key,index in indexes.items()}

    @classmethod
    def from_qwen(cls, config_path, indexes, *, model_path_override=None, debug_model_output=False):
        from .neo_backend import QwenStructuredBackend
        backend = QwenStructuredBackend(config_path, model_path_override=model_path_override)
        return cls(backend.chat, indexes, token_count_fn=backend.count_tokens,
                   max_input_tokens=min(5632, backend.input_budget), debug_model_output=debug_model_output,
                   structured_chat_fn=backend.chat)

    def ground(self, request, context):
        started = time.perf_counter()
        self._stage_started = started
        self.last_diagnostics = dict(mode='llm_verified', calls=0, status='failed', stage='prompt',
            prompt_version=PROMPT_VERSION, input_budget=self.max_input_tokens, stage_timings_ms={})
        try:
            return self._ground(request, context)
        finally:
            self._finish_stage()
            self.last_diagnostics['elapsed_ms'] = (time.perf_counter() - started) * 1000

    def _finish_stage(self, next_stage=None):
        now = time.perf_counter()
        stage = self.last_diagnostics['stage']
        if stage != 'complete':
            timings = self.last_diagnostics['stage_timings_ms']
            timings[stage] = timings.get(stage, 0.0) + (now - self._stage_started) * 1000
        self._stage_started = now
        if next_stage is not None:
            self.last_diagnostics['stage'] = next_stage

    def _ground(self, request, context):
        index = self.indexes[request.business_id]
        if context.business_id != request.business_id:
            raise ValueError('business mismatch')
        evidence = index.prompt_context(request.question)
        refs = ReferenceMap(index)
        if self.compact_proposals:
            evidence = refs.context(evidence)
        system = SYSTEM
        evidence, user, tokens, budget_info = fit_context(evidence, request.question, request.as_of_date,
            system, self.token_count_fn, self.max_input_tokens)
        self.last_diagnostics.update(input_tokens=tokens, input_budget=self.max_input_tokens,
            context_budget=budget_info, schema_tables_sent=[t['name'] for t in evidence['tables']])
        schema = refs.decoding_schema(evidence, index) if self.compact_proposals else Proposal.model_json_schema()
        self.last_diagnostics.update(prompt_version=PROMPT_VERSION, constrained_decoding=self.structured_chat_fn is not None)
        if self.debug_model_output:
            self.last_diagnostics['prompt'] = dict(system=system, user=user)
            self.last_diagnostics['reference_map'] = dict(tables=refs.tables, columns=refs.columns)
            self.last_diagnostics['decoding_schema'] = schema
        self.last_diagnostics['calls'] = 1
        self._finish_stage('inference')
        raw = self.structured_chat_fn(system, user, schema) if self.structured_chat_fn else self.chat_fn(system, user)
        # Metadata is owned by the backend instance or the injected test callable.
        owner = getattr(self.chat_fn, '__self__', self.chat_fn)
        self.last_diagnostics.update(getattr(owner, 'last_generation', {}))
        if self.debug_model_output:
            self.last_diagnostics['raw_response'] = raw[:50000]
        self.last_diagnostics['response_chars'] = len(raw)
        if self.last_diagnostics.get('finish_reason') == 'length':
            raise ValueError('GROUNDING_OUTPUT_TRUNCATED: generation reached max_new_tokens')
        self._finish_stage('proposal_parse')
        if len(raw) > 50000:
            raise ValueError('proposal exceeds size limit')
        proposal, rejected = parse_partial_proposal(raw, refs if self.compact_proposals else None)
        self._finish_stage('verification')
        payload = verify_proposal(proposal, request, index, self.value_verifiers[request.business_id], rejected_claims=rejected)
        if budget_info['trimmed']:
            payload['assessment']['warnings'].append(dict(code='CONTEXT_PRUNED', refs=[],
                message='Optional context was omitted for budget; protected sources/columns were retained.'))
        self._finish_stage('complete')
        self.last_diagnostics.update(status='partial', fingerprint=index.fingerprint,
            rejected_claims=len(payload['assessment']['rejected_claims']),
            blocked_refs=len(payload['assessment']['blocked_refs']))
        return GroundedQuestion(question_id=request.question_id, business_id=request.business_id, question=request.question,
            as_of_date=request.as_of_date, intent=QuestionIntent(operation=OperationKind(proposal.operation), answer_type_hint=AnswerTypeHint(proposal.answer_type)),
            resolved_time_ranges=(), selected_schema=SelectedSchema(primary_table=None), matched_values=(), answer_type_hint=AnswerTypeHint(proposal.answer_type),
            evidence_requirements=(), coverage_status=CoverageStatus.UNKNOWN, grounding_source='llm_verified', planner_input=payload)
