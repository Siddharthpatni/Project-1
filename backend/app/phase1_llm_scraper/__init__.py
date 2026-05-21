"""
Phase 1 — LLM-based Scraper Generation.

Pipeline:
    URL ──▶ prompts.build_generation_prompt
        ──▶ generator.generate_scraper          (LLM call)
        ──▶ validator.validate                  (static safety check)
        ──▶ executor.execute                    (sandboxed run)
        ──▶ evaluator.evaluate                  (success? recall?)
        ──▶ feedback_loop.iterate               (retry with error context)

Utilities:
    pricing.MODEL_PRICING / calc_cost           (per-model cost estimation)
"""
