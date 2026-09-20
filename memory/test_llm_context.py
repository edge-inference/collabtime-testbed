#!/usr/bin/env python3
"""
Test LLM with Context Memory

Verify that an LLM can read from context memory and make decisions.

Usage:
    python test_llm_context.py
    python test_llm_context.py --dry-run
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.context_memory import ContextMemory
from memory.selector import ContextSelector, build_prompt
from memory.schema import RobotIntent, TaskStatus

MODEL_NAME = "Qwen/Qwen2.5-1.5B-Instruct"


def create_test_scenario() -> ContextMemory:
    """Create a realistic warehouse scenario."""
    ctx = ContextMemory()

    ctx.update_robot(1, x=2.0, y=3.0, theta=0.5, intent=RobotIntent.MOVING, current_task=5)
    ctx.update_robot(2, x=3.0, y=3.5, theta=1.2, intent=RobotIntent.WORKING, current_task=3)
    ctx.update_robot(3, x=8.0, y=1.0, theta=0.0, intent=RobotIntent.IDLE)
    ctx.update_robot(4, x=2.5, y=2.5, theta=0.8, intent=RobotIntent.MOVING, current_task=7)

    ctx.update_task(3, location_x=3.0, location_y=4.0, location_node=13,
                    status=TaskStatus.IN_PROGRESS, assigned_robot=2, priority=2)
    ctx.update_task(5, location_x=4.0, location_y=3.0, location_node=14,
                    status=TaskStatus.CLAIMED, assigned_robot=1, priority=1)
    ctx.update_task(7, location_x=1.0, location_y=4.0, location_node=15,
                    status=TaskStatus.CLAIMED, assigned_robot=4, priority=1)
    ctx.update_task(9, location_x=0.0, location_y=2.0, location_node=10,
                    status=TaskStatus.PENDING, priority=3)
    ctx.update_task(11, location_x=4.0, location_y=4.0, location_node=19,
                    status=TaskStatus.PENDING, priority=1)

    ctx.update_region("aisle-2", jam_signal=0.8)
    ctx.update_region("aisle-3", jam_signal=0.3)

    return ctx


def run_inference(ctx: ContextMemory):
    """Run inference with Qwen2.5-1.5B."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"Loading {MODEL_NAME}...")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True
    )

    selector = ContextSelector(ctx)
    context_text = selector.select(my_robot_id=1, my_x=2.0, my_y=3.0, radius=5.0)

    print("\n" + "=" * 60)
    print("CONTEXT:")
    print(context_text)
    print("=" * 60)

    questions = [
        "Based on the nearby robots, should I adjust my speed or path?",
        "Which available task should I pick next and why?",
    ]

    for question in questions:
        print(f"\nQUESTION: {question}")
        print("-" * 40)

        prompt = build_prompt(context_text, question)
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

        outputs = model.generate(
            **inputs,
            max_new_tokens=150,
            temperature=0.7,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id
        )

        response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        answer = response.split("ANSWER (be concise):")[-1].strip()
        print(f"ANSWER: {answer}")


def dry_run(ctx: ContextMemory):
    """Show context without calling LLM."""
    print("=" * 60)
    print("CONTEXT MEMORY STATS:")
    print("=" * 60)
    for k, v in ctx.stats().items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("CONTEXT TEXT:")
    print("=" * 60)
    selector = ContextSelector(ctx)
    context_text = selector.select(my_robot_id=1, my_x=2.0, my_y=3.0, radius=5.0)
    print(context_text)

    print("\n" + "=" * 60)
    print("FULL PROMPT:")
    print("=" * 60)
    print(build_prompt(context_text, "What should I do next?"))


def main():
    parser = argparse.ArgumentParser(description="Test LLM with Context Memory")
    parser.add_argument("--dry-run", action="store_true", help="Show context without LLM")
    args = parser.parse_args()

    print("Creating test scenario...")
    ctx = create_test_scenario()

    if args.dry_run:
        dry_run(ctx)
    else:
        run_inference(ctx)


if __name__ == "__main__":
    main()
